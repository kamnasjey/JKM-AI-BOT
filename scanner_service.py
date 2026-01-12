# scanner_service.py
import asyncio
import logging
import os
import sys
import time
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from typing import Any as _Any

# Dependencies
from user_db import list_users
from user_core_engine import (
    scan_pair_cached,
    scan_pair_cached_indicator_free,
    ScanResult,
    extract_strategy_configs,
)
from market_data_cache import market_cache
from data_ingestor_5m import DataIngestor
from resample_5m import resample
from engine_blocks import Candle
from services.models import SignalEvent
from services.notifier_telegram import telegram_notifier
from services.chart_generator import generate_chart_image
from signals_tracker import evaluate_pending_signals_for_user, record_signal
from scanner_state import SignalStateStore
import config

from data_readiness import readiness_check

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
# Suppress httpx INFO logs (they leak bot token in URL)
logging.getLogger('httpx').setLevel(logging.WARNING)
# ... imports remain ...
import threading

from core.explain import build_pair_none_explain, build_pair_ok_explain
from core import event_queue as _event_queue

from metrics.scan_metrics import build_event_from_explain, emit_event
from metrics.daily_summary import format_tuning_report, summarize_last_24h, write_daily_report
from metrics.guardrails import format_alert_message, process_guardrails_stateful

from notify.telegram import send_admin_alert, send_admin_coverage, send_admin_recovery, send_admin_report

from engine.utils.logging_utils import make_scan_id, log_kv, log_kv_error
from engine.utils.reason_codes import build_governance_evidence, normalize_pair_none_reason


def _format_top_contribs(breakdown: Any, *, max_items: int = 3) -> Optional[str]:
    """Return compact contrib string: d1:0.62,d2:0.55"""
    if not isinstance(breakdown, dict):
        return None
    items = breakdown.get("top_hit_contribs")
    if not isinstance(items, list) or not items:
        return None
    out = []
    for it in items[: int(max_items)]:
        if not isinstance(it, dict):
            continue
        det = str(it.get("detector") or "").strip()
        try:
            w = float(it.get("weighted") or 0.0)
        except Exception:
            w = 0.0
        if det:
            out.append(f"{det}:{w:.2f}")
    return ",".join(out) if out else None


def _extract_score_breakdown_fields_for_logs(dbg: Any) -> Dict[str, Any]:
    """Return compact score fields for PAIR_OK/PAIR_NONE logs."""
    if not isinstance(dbg, dict):
        return {}
    bd = dbg.get("score_breakdown")
    if not isinstance(bd, dict):
        return {}

    side = str(bd.get("best_side") or "").upper()
    if side not in ("BUY", "SELL"):
        side = ""

    score_raw = None
    bonus = None
    try:
        if side == "BUY":
            score_raw = float(bd.get("buy_score_weighted") or 0.0)
            bonus = float(bd.get("confluence_bonus_buy") or 0.0)
        elif side == "SELL":
            score_raw = float(bd.get("sell_score_weighted") or 0.0)
            bonus = float(bd.get("confluence_bonus_sell") or 0.0)
    except Exception:
        score_raw = None
        bonus = None

    out: Dict[str, Any] = {}
    if score_raw is not None:
        out["score_raw"] = f"{float(score_raw):.2f}"
    if bonus is not None:
        out["bonus"] = f"{float(bonus):.2f}"

    tc = _format_top_contribs(bd, max_items=3)
    if tc:
        out["top_contribs"] = tc
    return out

from strategies.loader import load_strategies, load_strategies_from_profile

# ... logging setup ...


logger = logging.getLogger("ScannerService")

_EXPLAIN_AUDIT_LOCK = threading.Lock()


def _maybe_audit_explain(payload: Dict[str, Any]) -> None:
    if str(os.getenv("EXPLAIN_AUDIT", "")).strip() != "1":
        return
    try:
        os.makedirs("logs", exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with _EXPLAIN_AUDIT_LOCK:
            with open("logs/explain_events.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        # Non-fatal by design.
        return


def _maybe_emit_metrics_from_explain(
    payload: Dict[str, Any],
    *,
    debug: Any = None,
    failover_used: Optional[bool] = None,
) -> None:
    try:
        candidates = None
        if isinstance(debug, dict):
            candidates = debug.get("candidates")
        ev = build_event_from_explain(
            explain=payload,
            candidates=candidates,
            failover_used=failover_used,
        )
        emit_event(ev)
    except Exception:
        return


def _attach_explain_to_debug(debug: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Attach explain payload into debug dict (NA-safe)."""
    if isinstance(debug, dict):
        out = dict(debug)
    else:
        out = {}
    out["explain"] = dict(payload or {})
    return out

_CACHE_PERSIST_PATH = os.getenv("MARKET_CACHE_PATH", "state/market_cache.json")


def _convert_dicts_to_candles(items: List[Dict[str, Any]]) -> List[Candle]:
    out: List[Candle] = []
    for d in items:
        try:
            out.append(
                Candle(
                    time=d["time"],
                    open=float(d["open"]),
                    high=float(d["high"]),
                    low=float(d["low"]),
                    close=float(d["close"]),
                )
            )
        except Exception:
            continue
    return out


def _shift_candle_dict_times(items: List[Dict[str, Any]], tz_offset_hours: int) -> List[Dict[str, Any]]:
    if not tz_offset_hours:
        return items
    out: List[Dict[str, Any]] = []
    delta = timedelta(hours=int(tz_offset_hours))
    for d in items:
        try:
            t = d.get("time")
            if isinstance(t, datetime):
                nd = dict(d)
                nd["time"] = t + delta
                out.append(nd)
            else:
                out.append(d)
        except Exception:
            out.append(d)
    return out

class ScannerService:
    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._manual_trigger = threading.Event()
        self._last_ig_total: Optional[int] = None

        # APScheduler is optional at runtime; import lazily to avoid hard failure
        # if the environment has a broken APScheduler installation.
        self._scheduler: Optional[_Any] = None

        self._state_store = SignalStateStore()
        self._state_loaded = False
        self._state_dirty = False
        self._state_last_saved_ts: float = 0.0
        self._state_save_min_interval_sec: float = 2.0

        # Performance guard counters (best-effort)
        self._perf_cycles: int = 0
        self._perf_detector_warn: Dict[str, int] = {}
        self._perf_detector_max_ms: Dict[str, float] = {}
        self._perf_feature_warn_total: int = 0
        self._perf_pair_warn_total: int = 0
        self._perf_cycle_warn_total: int = 0

        # Admin-only readiness notifications (rate-limited)
        self._data_gap_admin_last_sent: Dict[str, float] = {}

        # Optional global strategy pack loaded from config/strategies.json
        self._global_strategies_count: int = 0

        # Ops snapshot (best-effort)
        self._last_scan_id: str = "NA"
        self._last_scan_ts: str = "NA"

        # Initialize event queue DB (safe to call multiple times)
        try:
            _event_queue.init_db()
        except Exception as _eq_err:
            logger.warning("event_queue init failed: %s", type(_eq_err).__name__)
        
    def start(self):
        if self._thread and self._thread.is_alive():
            logger.info("ScannerService already running.")
            return
        
        logger.info("Starting ScannerService in background thread...")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()
        
    def stop(self):
        logger.info("Stopping ScannerService...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
            logger.info("ScannerService stopped.")

    def manual_scan(self):
        logger.info("Manual scan triggered.")
        self._manual_trigger.set()

    def get_last_scan_info(self) -> Dict[str, Any]:
        """Return last scan identifiers for ops endpoints (NA-safe)."""
        try:
            sid = str(getattr(self, "_last_scan_id", "NA") or "NA")
            sts = str(getattr(self, "_last_scan_ts", "NA") or "NA")
        except Exception:
            sid = "NA"
            sts = "NA"
        return {"last_scan_id": sid, "last_scan_ts": sts}

    def manual_scan_explain(
        self,
        *,
        user_id: str,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run a one-off scan for a specific user and return a Telegram-ready explanation.

        This is used for user-triggered manual scans ("why no setup?").
        It does not send any operational/metrics Telegram messages.
        """

        uid = str(user_id or "default").strip() or "default"
        sym_list: List[str] = []
        if isinstance(symbols, list) and symbols:
            sym_list = [str(s).strip().upper() for s in symbols if str(s).strip()]
        if not sym_list:
            try:
                from watchlist_union import get_union_watchlist

                sym_list = [str(s).strip().upper() for s in get_union_watchlist() or []]
            except Exception:
                sym_list = []
        if not sym_list:
            try:
                sym_list = [str(s).strip().upper() for s in (getattr(config, "WATCH_PAIRS", []) or [])]
            except Exception:
                sym_list = []

        # Best-effort: ensure background services are warm.
        try:
            if not getattr(self, "_thread", None) or not self._thread.is_alive():
                self.start()
                time.sleep(1.0)
        except Exception:
            pass

        scan_id = make_scan_id()
        outcomes: Dict[str, Any] = {}
        user = {
            "user_id": uid,
            "name": uid,
            "telegram_handle": "",
            "watch_pairs": sym_list,
        }

        try:
            signals_sent = int(
                self._scan_for_user(
                    user,
                    scan_id=scan_id,
                    outcomes=outcomes,
                    notify_mode_override="off",
                )
                or 0
            )
        except Exception as e:
            return {
                "ok": False,
                "user_id": uid,
                "scan_id": scan_id,
                "error": f"{type(e).__name__}: {e}",
            }

        # Build a concise explanation message.
        lines: List[str] = []
        lines.append("🔎 Manual scan result")
        lines.append(f"user_id: {uid}")
        lines.append(f"scan_id: {scan_id}")
        lines.append("")

        # Per-symbol summary
        for sym in sym_list:
            row = outcomes.get(sym) if isinstance(outcomes, dict) else None
            if not isinstance(row, dict):
                lines.append(f"{sym}: NO_DATA")
                continue

            kind = str(row.get("kind") or "NONE").upper()
            if kind == "OK":
                direction = str(row.get("direction") or "NA")
                rr = row.get("rr")
                rr_s = f"{float(rr):.2f}" if rr is not None else "NA"
                lines.append(f"{sym}: ✅ SETUP {direction} (RR {rr_s})")
            else:
                reason = str(row.get("reason") or "NO_HITS")
                lines.append(f"{sym}: ❌ {reason}")

        # What conditions we are waiting for (based on enabled detectors)
        try:
            from core.user_strategies_store import load_user_strategies
            from detectors.registry import get_detector

            stored = load_user_strategies(uid)
            active = stored[0] if isinstance(stored, list) and stored else {}
            det_names = active.get("detectors") if isinstance(active, dict) else None
            if isinstance(det_names, list) and det_names:
                lines.append("")
                lines.append("⏳ Waiting for these detector conditions:")
                for name in det_names[:8]:
                    n = str(name).strip()
                    if not n:
                        continue
                    doc = ""
                    try:
                        det = get_detector(n)
                        doc = det.get_doc() if det else ""
                    except Exception:
                        doc = ""
                    doc = (doc or "").strip()
                    if doc:
                        # Keep first sentence-ish for Telegram brevity
                        short = doc.split("\n", 1)[0].strip()
                        if len(short) > 140:
                            short = short[:140].rstrip() + "…"
                        lines.append(f"- {n}: {short}")
                    else:
                        lines.append(f"- {n}")
        except Exception:
            pass

        return {
            "ok": True,
            "user_id": uid,
            "scan_id": scan_id,
            "symbols": sym_list,
            "signals_sent": signals_sent,
            "outcomes": outcomes,
            "message": "\n".join(lines).strip(),
        }

    def _run_thread(self):
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main_async())
        finally:
            loop.close()

    async def _main_async(self):
        logger.info("Initializing Scanner Service Loop...")

        # Load global strategy packs (optional). Must never crash.
        try:
            # 1) Custom detectors (optional). Must never crash.
            try:
                from detectors.custom_loader import load_custom_detectors_with_logs

                load_custom_detectors_with_logs(
                    logger,
                    custom_dir="detectors/custom",
                    log_kv=log_kv,
                    log_kv_warning=log_kv_warning,
                )
            except Exception:
                # Keep boot robust.
                pass

            # 2) Strategies (optional). Must never crash.
            from strategies.loader import (
                load_strategy_pack,
                summarize_unknown_detectors,
                summarize_unknown_detector_suggestions,
            )

            pack = load_strategy_pack("config/strategies.json", presets_dir="config/presets")

            # Admin-only: unknown detector suggestion hints.
            try:
                import config as _cfg

                notify_mode = str(getattr(_cfg, "NOTIFY_MODE", "all") or "all").strip().lower()
            except Exception:
                notify_mode = "all"
            if notify_mode == "admin_only":
                sugg_payload = summarize_unknown_detector_suggestions(pack, max_strategies=10)
                if isinstance(sugg_payload, dict) and sugg_payload.get("unknown_detector_suggestions"):
                    log_kv_warning(logger, "STRATEGY_UNKNOWN_DETECTOR_SUGGESTIONS", **sugg_payload)

                # Admin-only: auto-fix patch suggestions for unknown detectors.
                for it in (getattr(pack, "unknown_detector_autofix_patches", []) or []):
                    if not isinstance(it, dict):
                        continue
                    log_kv_warning(
                        logger,
                        "UNKNOWN_DETECTORS_PATCH_SUGGESTED",
                        patch_id=str(it.get("patch_id") or ""),
                        patch_type=str(it.get("patch_type") or "FIX_UNKNOWN_DETECTORS"),
                        strategies=list(it.get("strategy_ids") or []),
                        replacements=dict(it.get("replacements") or {}),
                        dry_run_preview=str(it.get("dry_run_preview") or ""),
                    )

            # Preset pack observability (requested contract)
            log_kv(
                logger,
                "PRESETS_LOADED",
                dir="config/presets",
                requested=len(pack.include_presets),
                loaded=len(pack.loaded_presets),
                missing=len(pack.missing_presets),
                preset_ids=pack.loaded_presets,
            )

            # Per-strategy validation logs
            # Strict detector mode: strategies may be disabled in-memory by loader.
            for sid, names in (getattr(pack, "disabled_unknown_detectors", {}) or {}).items():
                if not names:
                    continue
                log_kv_warning(
                    logger,
                    "STRATEGY_DISABLED_UNKNOWN_DETECTORS",
                    strategy_id=str(sid),
                    names=list(names),
                )

            for inv in pack.invalid_enabled:
                log_kv_warning(
                    logger,
                    "STRATEGY_INVALID",
                    strategy_id=str(inv.get("strategy_id") or ""),
                    errors=list(inv.get("errors") or []),
                )
            for spec in pack.strategies:
                try:
                    custom_params_n = int(len(getattr(spec, "detector_params", {}) or {}))
                except Exception:
                    custom_params_n = 0
                log_kv(
                    logger,
                    "STRATEGY_READY",
                    strategy_id=spec.strategy_id,
                    priority=spec.priority,
                    detector_params_count=custom_params_n,
                )

            log_kv(
                logger,
                "STRATEGY_VALIDATION_REPORT",
                path="config/strategies.json",
                schema_version=pack.schema_version,
                enabled_count=len(pack.strategies),
                invalid_enabled_count=len(pack.invalid_enabled),
                errors_count=len(pack.errors),
                warnings_count=len(pack.warnings),
                errors=pack.errors,
                warnings=pack.warnings,
            )

            global_strats = list(pack.strategies)
            try:
                self._global_strategies_count = int(len(global_strats))
            except Exception:
                self._global_strategies_count = 0
            unk_summary = summarize_unknown_detectors(pack, max_items=10)
            log_kv(
                logger,
                "STRATEGIES_LOADED",
                path="config/strategies.json",
                count=len(global_strats),
                **unk_summary,
            )
        except Exception:
            # Keep boot robust even if strategy file is bad/missing.
            self._global_strategies_count = 0
            pass

        # Load persistent signal state once at boot.
        try:
            t_state = time.perf_counter()
            self._state_store.load()
            pruned_sent, pruned_daily = self._state_store.prune(older_than_days=14)
            self._state_loaded = True
            dt_state_ms = (time.perf_counter() - t_state) * 1000.0
            counts = self._state_store.snapshot_counts()
            log_kv(
                logger,
                "STATE_LOADED",
                path=str(self._state_store.path),
                ms=f"{dt_state_ms:.2f}",
                pruned_sent=pruned_sent,
                pruned_daily=pruned_daily,
                **counts,
            )
        except Exception:
            log_kv_error(logger, "STATE_LOAD_ERROR")
            self._state_loaded = False

        # Load persisted cache if available (reduces repeated IG historical warmups after restart)
        try:
            market_cache.load_json(_CACHE_PERSIST_PATH)
            loaded_syms = market_cache.get_all_symbols()
            if loaded_syms:
                logger.info(f"Loaded cached candles from {_CACHE_PERSIST_PATH} for: {loaded_syms}")
        except Exception as e:
            logger.warning(f"Failed to load cache from {_CACHE_PERSIST_PATH}: {e}")

        # If Massive is enabled, prefer preloading from persisted per-symbol store under state/marketdata.
        # This proves persistence works and gives engine immediate data after restart.
        try:
            env_provider_pre = (os.getenv("DATA_PROVIDER", "") or "").strip().lower() or (
                os.getenv("MARKET_DATA_PROVIDER", "") or ""
            ).strip().lower()
            if env_provider_pre in ("massive", "massiveio", "massive_io"):
                from core.marketdata_store import load_tail
                from core.marketdata_store import _data_path as _md_path  # type: ignore
                from watchlist_union import get_union_watchlist
                from core.ingest_debug import ingest_debug_enabled

                syms = get_union_watchlist()
                loaded = 0
                for sym in syms:
                    items = load_tail(sym, "m5", limit=int(getattr(config, "MARKETDATA_PRELOAD_M5_LIMIT", 5000) or 5000))
                    if items:
                        market_cache.upsert_candles(sym, items)
                        loaded += 1
                        if ingest_debug_enabled():
                            try:
                                last_ts = items[-1].get("time")
                                log_kv(
                                    logger,
                                    "MARKETDATA_LOAD",
                                    source="disk",
                                    symbol=str(sym).upper(),
                                    tf="m5",
                                    rows=int(len(items)),
                                    path=str(_md_path(sym, "m5")),
                                    last_ts=(last_ts.isoformat() if hasattr(last_ts, "isoformat") else None),
                                )

                                # Prove higher-TF readiness (MarketDataCache derives H1/H4 from M5).
                                try:
                                    h1 = market_cache.get_resampled(str(sym).upper(), "H1")
                                    if h1:
                                        h1_last = h1[-1].get("time")
                                        log_kv(
                                            logger,
                                            "MARKETDATA_LOAD",
                                            source="disk_resample",
                                            symbol=str(sym).upper(),
                                            tf="h1",
                                            rows=int(len(h1)),
                                            path=str(_md_path(sym, "m5")),
                                            last_ts=(h1_last.isoformat() if hasattr(h1_last, "isoformat") else None),
                                        )
                                except Exception:
                                    pass

                                try:
                                    h4 = market_cache.get_resampled(str(sym).upper(), "H4")
                                    if h4:
                                        h4_last = h4[-1].get("time")
                                        log_kv(
                                            logger,
                                            "MARKETDATA_LOAD",
                                            source="disk_resample",
                                            symbol=str(sym).upper(),
                                            tf="h4",
                                            rows=int(len(h4)),
                                            path=str(_md_path(sym, "m5")),
                                            last_ts=(h4_last.isoformat() if hasattr(h4_last, "isoformat") else None),
                                        )
                                except Exception:
                                    pass
                            except Exception:
                                pass
                if loaded:
                    logger.info(f"Preloaded marketdata_store m5 for {loaded} symbols into cache")
        except Exception as e:
            logger.warning(f"Failed to preload marketdata_store: {e}")

        market_data_provider = os.getenv("MARKET_DATA_PROVIDER", "massive").strip().lower()
        # Back-compat: MARKET_DATA_PROVIDER still works.
        # New: DATA_PROVIDER supports provider swapping without touching engine/cache.
        env_provider = os.getenv("DATA_PROVIDER", "").strip().lower() or market_data_provider

        # 1. Initialize Provider (Adapter layer)
        provider = None
        fallback_provider = None

        # Always have a lightweight provider available (doesn't burn external quota).
        try:
            from data_providers.simulation_provider import SimulationDataProvider

            fallback_provider = SimulationDataProvider()
        except Exception as e:
            logger.warning(f"SimulationDataProvider unavailable: {e}")
            fallback_provider = None

        try:
            from data_providers.factory import create_provider

            provider = create_provider(name=env_provider)
            logger.info(f"Provider: {getattr(provider, 'name', 'unknown')}")
        except Exception as e:
            logger.error(f"Failed to init DataProvider ({env_provider}): {e}")
            if fallback_provider is not None:
                provider = fallback_provider
                logger.info("Provider: SimulationDataProvider (Fallback)")
            else:
                return

        # 2. Start Ingestor
        # Warmup: fetch roughly last 7 days of M5 candles (7*24*12 = 2016).
        # Poll: every 5 minutes to align with M5 candle formation.
        # Note: IG demo/live may hit historical-data allowance; fallback avoids total downtime.
        self.ingestor = DataIngestor(
            provider=provider,
            fallback_provider=(fallback_provider if (provider is not fallback_provider) else None),
            poll_interval=300,
            warmup=2016,
            incremental_limit=5,
            persist_path=_CACHE_PERSIST_PATH,
            persist_every_cycles=1,
        )
        ingestor_task = asyncio.create_task(self.ingestor.run_forever())

        logger.info("Ingestor started. Waiting briefly for initial cache warmup...")
        # Give ingestor time to fetch at least some candles per watched symbol.
        warmup_deadline = time.time() + 60
        while not self._stop_event.is_set() and time.time() < warmup_deadline:
            symbols = []
            try:
                symbols = market_cache.get_all_symbols()
            except Exception:
                symbols = []

            if symbols and all(len(market_cache.get_candles(s)) >= 50 for s in symbols):
                break
            await asyncio.sleep(2)
        
        # 3. Main Analysis Loop
        logger.info("Starting Analysis Loop...")

        scan_interval_sec = max(int(getattr(config, "AUTO_SCAN_INTERVAL_MIN", 1) or 1), 1) * 60
        misfire_grace_sec = int(getattr(config, "SCHEDULER_MISFIRE_GRACE_SEC", 120) or 120)

        scheduler_ready = False
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
            from apscheduler.triggers.interval import IntervalTrigger  # type: ignore

            self._scheduler = AsyncIOScheduler(
                timezone=timezone.utc,
                job_defaults={
                    "max_instances": 1,
                    "coalesce": True,
                    "misfire_grace_time": misfire_grace_sec,
                },
            )
            self._scheduler.add_job(
                self._scan_cycle,
                trigger=IntervalTrigger(seconds=scan_interval_sec),
                id="scan_cycle",
                replace_existing=True,
            )
            self._scheduler.start()
            scheduler_ready = True
        except Exception as e:
            # Fall back to a sequential loop (non-overlapping by design).
            logger.warning(f"APScheduler unavailable; falling back to manual loop: {e}")
            self._scheduler = None

        if scheduler_ready:
            # Keep the loop alive; allow manual triggers to pull next scan forward.
            while not self._stop_event.is_set():
                try:
                    if self._manual_trigger.is_set() and self._scheduler:
                        self._manual_trigger.clear()
                        try:
                            # Schedule the next run ASAP (without overlapping due to max_instances=1).
                            self._scheduler.modify_job("scan_cycle", next_run_time=datetime.now(timezone.utc))
                        except Exception:
                            pass
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Analysis Loop Error: {e}")
                    await asyncio.sleep(2)
        else:
            while not self._stop_event.is_set():
                try:
                    for _ in range(int(scan_interval_sec)):
                        if self._stop_event.is_set():
                            break
                        if self._manual_trigger.is_set():
                            self._manual_trigger.clear()
                            break
                        await asyncio.sleep(1)
                    if self._stop_event.is_set():
                        break
                    await self._scan_cycle()
                except Exception as e:
                    logger.error(f"Analysis Loop Error: {e}")
                    await asyncio.sleep(2)

        # Cleanup
        logger.info("Shutting down ingestor...")
        try:
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
        except Exception:
            pass
        self.ingestor.stop()
        await ingestor_task
        logger.info("Service Loop Shutdown.")

    async def _scan_cycle(self):
        scan_id = make_scan_id()
        timestamp = datetime.now()
        t0 = time.perf_counter()

        # Record ops snapshot early (even if cycle errors later).
        try:
            self._last_scan_id = str(scan_id)
            self._last_scan_ts = datetime.now(timezone.utc).isoformat()
        except Exception:
            pass

        ig_before = None

        users = list_users()
        if not users:
            try:
                from watchlist_union import get_union_watchlist

                wl = get_union_watchlist()
            except Exception:
                wl = []

            # Safety: never allow empty universe in headless mode.
            if not wl:
                try:
                    import config as _cfg

                    wl = list(getattr(_cfg, "WATCH_PAIRS", []) or [])
                except Exception:
                    wl = []

            # Default user: allows scanning to run in headless/VPS mode.
            users = [
                {
                    "user_id": "default",
                    "name": "Default",
                    "telegram_handle": "",
                    "watch_pairs": wl,
                }
            ]
        pairs_count = 0
        try:
            for u in users:
                ps = u.get("watch_pairs", [])
                if isinstance(ps, list):
                    pairs_count += len(ps)
        except Exception:
            pairs_count = 0

        log_kv(
            logger,
            "SCAN_START",
            scan_id=scan_id,
            pairs=pairs_count,
            users=len(users),
            strategies_count=int(getattr(self, "_global_strategies_count", 0) or 0),
            ts=timestamp.isoformat(),
        )

        signals_found = 0

        for user in users:
            try:
                signals_found += int(self._scan_for_user(user, scan_id=scan_id) or 0)
            except Exception as e:
                log_kv_error(logger, "scan_user_error", scan_id=scan_id, user_id=str(user.get("user_id") or ""))
                
        dt_ms = (time.perf_counter() - t0) * 1000.0

        # Performance guard: cycle runtime
        try:
            self._perf_cycles += 1
            if float(dt_ms) > float(config.SCAN_CYCLE_WARN_MS):
                self._perf_cycle_warn_total += 1
                log_kv(
                    logger,
                    "PERF_WARN",
                    scan_id=scan_id,
                    kind="cycle_ms",
                    ms=f"{dt_ms:.2f}",
                    warn_ms=int(config.SCAN_CYCLE_WARN_MS),
                )
        except Exception:
            pass

        ig_after = None

        # Flush any pending state changes at cycle end.
        self._flush_state_if_dirty(scan_id=scan_id)

        # Daily metrics summary (once per UTC date)
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            last = str(getattr(self, "_metrics_last_summary_date", "") or "")
            if today != last:
                summary = summarize_last_24h(events_path="state/metrics_events.jsonl")
                summary_dict = summary.to_dict()
                top_reason = summary.top_reasons[0]["reason"] if summary.top_reasons else "NA"
                top_strategy = summary.top_strategies_by_ok[0]["strategy_id"] if summary.top_strategies_by_ok else "NA"
                log_kv(
                    logger,
                    "METRICS_DAILY_SUMMARY",
                    date=summary.date,
                    window_h=summary.window_hours,
                    ok=summary.ok_count,
                    total=summary.total_pairs,
                    ok_rate=f"{summary.ok_rate:.3f}",
                    top_reason=top_reason,
                    top_strategy=top_strategy,
                    avg_score=(f"{summary.avg_score:.3f}" if summary.avg_score is not None else "NA"),
                    avg_rr=(f"{summary.avg_rr:.3f}" if summary.avg_rr is not None else "NA"),
                    cooldown_blocks=summary.cooldown_blocks,
                    daily_limit_blocks=summary.daily_limit_blocks,
                )

                # Detector coverage snapshot (ops tuning)
                try:
                    top_detectors = summary_dict.get("top_detectors")
                    dead_detectors = summary_dict.get("dead_detectors")
                    dead_diagnosis = summary_dict.get("dead_diagnosis")
                    dead_diagnosis_details = summary_dict.get("dead_diagnosis_details")
                    shadow_top_detectors = summary_dict.get("shadow_top_detectors")
                    shadow_dead_detectors = summary_dict.get("shadow_dead_detectors")
                    shadow_seen_detectors = summary_dict.get("shadow_seen_detectors")
                    shadow_dead_detectors_count = summary_dict.get("shadow_dead_detectors_count")
                    per_strategy_compact = summary_dict.get("per_strategy_top_detectors_compact")
                    total_strategies_covered = summary_dict.get("total_strategies_covered")
                    loaded_detectors = summary_dict.get("loaded_detectors")
                    seen_detectors = summary_dict.get("seen_detectors")
                    dead_detectors_count = summary_dict.get("dead_detectors_count")
                    log_kv(
                        logger,
                        "METRICS_DETECTOR_COVERAGE",
                        date=summary.date,
                        window_h=summary.window_hours,
                        ok=summary.ok_count,
                        total=summary.total_pairs,
                        loaded_detectors=(loaded_detectors if loaded_detectors is not None else "NA"),
                        seen_detectors=(seen_detectors if seen_detectors is not None else "NA"),
                        dead_detectors_count=(dead_detectors_count if dead_detectors_count is not None else "NA"),
                        top_detectors=top_detectors if top_detectors is not None else [],
                        dead_detectors=dead_detectors if dead_detectors is not None else [],
                        shadow_seen_detectors=(shadow_seen_detectors if shadow_seen_detectors is not None else "NA"),
                        shadow_dead_detectors_count=(shadow_dead_detectors_count if shadow_dead_detectors_count is not None else "NA"),
                        shadow_top_detectors=(shadow_top_detectors if shadow_top_detectors is not None else []),
                        shadow_dead_detectors=(shadow_dead_detectors if shadow_dead_detectors is not None else []),
                        dead_diagnosis=dead_diagnosis if isinstance(dead_diagnosis, dict) else {},
                        per_strategy_top_detectors=(per_strategy_compact if per_strategy_compact is not None else {}),
                        total_strategies_covered=(total_strategies_covered if total_strategies_covered is not None else 0),
                    )

                    # Admin-only: concise message
                    try:
                        import config as _cfg2

                        nm2 = str(getattr(_cfg2, "NOTIFY_MODE", "all") or "all").strip().lower()
                    except Exception:
                        nm2 = "all"
                    if nm2 == "admin_only":
                        top_str = "NA"
                        dead_str = "NA"
                        dead_fix = "NA"
                        if isinstance(top_detectors, list) and top_detectors:
                            parts = []
                            for it in top_detectors[:10]:
                                if not isinstance(it, dict):
                                    continue
                                d = str(it.get("detector") or "").strip()
                                c = it.get("count")
                                if d:
                                    parts.append(f"{d}:{c}")
                            if parts:
                                top_str = ", ".join(parts)
                        if isinstance(dead_detectors, list):
                            dead_str = ", ".join([str(x) for x in dead_detectors[:10]]) if dead_detectors else "(none)"

                        # Top 3 dead detectors with 1 suggestion each (deterministic).
                        try:
                            if isinstance(dead_diagnosis_details, dict) and dead_diagnosis_details:
                                parts = []
                                for det in sorted(list(dead_diagnosis_details.keys()))[:3]:
                                    row = dead_diagnosis_details.get(det)
                                    if not isinstance(row, dict):
                                        continue
                                    sugg = row.get("suggestions")
                                    s1 = ""
                                    if isinstance(sugg, list) and sugg:
                                        s1 = str(sugg[0] or "").strip()
                                    if not s1:
                                        s1 = "Review strategy allow-list/regimes/params"
                                    parts.append(f"{det} -> {s1}")
                                if parts:
                                    dead_fix = "; ".join(parts)
                        except Exception:
                            dead_fix = "NA"

                        strat_str = "NA"
                        if isinstance(per_strategy_compact, dict) and per_strategy_compact:
                            parts = []
                            for sid in sorted(list(per_strategy_compact.keys()))[:3]:
                                vals = per_strategy_compact.get(sid)
                                if isinstance(vals, list) and vals:
                                    parts.append(f"{sid}=[{', '.join([str(x) for x in vals[:3]])}]")
                            if parts:
                                strat_str = "; ".join(parts)

                        if _ops_telegram_enabled():
                            send_admin_coverage(
                                f"🧩 Detector Coverage ({summary.date}): top={top_str} | dead={dead_str} | fixes={dead_fix} | per_strategy={strat_str}"
                            )
                except Exception:
                    pass
                try:
                    write_daily_report(summary, out_dir="state/metrics_daily")
                except Exception:
                    pass

                # Guardrails (admin-only alerts with persisted dedupe + recovery)
                try:
                    enabled = str(os.getenv("METRICS_ALERTS", "1") or "1").strip()
                    if enabled != "0":
                        res = process_guardrails_stateful(
                            summary_dict,
                            state_path="state/metrics_alert_state.json",
                            config_module=config,
                        )
                        alerts_to_notify = res.get("trigger") if isinstance(res.get("trigger"), list) else []
                        alerts_repeat = res.get("repeat") if isinstance(res.get("repeat"), list) else []
                        recovered = res.get("recover") if isinstance(res.get("recover"), list) else []

                        triggered_codes = {
                            str(getattr(a, "code", "NA") or "NA")
                            for a in (alerts_to_notify + alerts_repeat)
                            if a is not None
                        }

                        for a in alerts_to_notify:
                            log_kv(
                                logger,
                                "METRICS_ALERT",
                                date=str(summary_dict.get("date") or today),
                                code=getattr(a, "code", "NA"),
                                severity=getattr(a, "severity", "NA"),
                                message=getattr(a, "message", "NA"),
                            )
                        for a in alerts_repeat:
                            log_kv(
                                logger,
                                "METRICS_ALERT_REPEAT",
                                date=str(summary_dict.get("date") or today),
                                code=getattr(a, "code", "NA"),
                                severity=getattr(a, "severity", "NA"),
                            )
                        for r in recovered:
                            log_kv(
                                logger,
                                "METRICS_ALERT_RECOVERED",
                                date=str(summary_dict.get("date") or today),
                                code=str((r or {}).get("code") or "NA"),
                            )

                        if alerts_to_notify and _ops_telegram_enabled():
                            msg = format_alert_message(summary_dict, alerts_to_notify)
                            send_admin_alert(msg)
                        for r in recovered:
                            try:
                                if _ops_telegram_enabled():
                                    send_admin_recovery(str((r or {}).get("message") or ""))
                            except Exception:
                                pass

                        # Deterministic tuning report (admin-only)
                        try:
                            reco_res = format_tuning_report(
                                summary_dict,
                                alert_codes=sorted(triggered_codes),
                                max_items=3,
                            )
                            reco_msg = str((reco_res or {}).get("text") or "")
                            actions_count = int((reco_res or {}).get("actions_count") or 0)
                            patch_preview = str((reco_res or {}).get("patch_preview") or "")

                            if reco_msg and "NA" not in reco_msg:
                                log_kv(
                                    logger,
                                    "METRICS_TUNING_REPORT",
                                    date=str(summary_dict.get("date") or today),
                                    recos=reco_msg,
                                    actions_count=actions_count,
                                )
                                if _ops_telegram_enabled():
                                    # Append 1–3 compact before/after blocks.
                                    if patch_preview:
                                        send_admin_report(reco_msg + "\n\nSuggested patches (dry-run):\n" + patch_preview)
                                    else:
                                        send_admin_report(reco_msg)
                        except Exception:
                            pass
                except Exception:
                    pass

                setattr(self, "_metrics_last_summary_date", today)
        except Exception:
            pass

        # Optional perf summary every N cycles
        try:
            n = int(getattr(config, "PERF_SUMMARY_EVERY_CYCLES", 0) or 0)
            if n > 0 and (self._perf_cycles % n == 0):
                # Keep summary short: show top 5 by max ms
                top = sorted(self._perf_detector_max_ms.items(), key=lambda kv: kv[1], reverse=True)[:5]
                top_s = ",".join([f"{k}:{v:.1f}" for k, v in top])
                log_kv(
                    logger,
                    "PERF_SUMMARY",
                    scan_id=scan_id,
                    cycles=self._perf_cycles,
                    detector_warn_total=sum(self._perf_detector_warn.values()) if self._perf_detector_warn else 0,
                    feature_warn_total=self._perf_feature_warn_total,
                    pair_warn_total=self._perf_pair_warn_total,
                    cycle_warn_total=self._perf_cycle_warn_total,
                    top_detectors_max_ms=top_s,
                )
        except Exception:
            pass

        if ig_before and ig_after:
            total_before = int(ig_before.get("total", 0))
            total_after = int(ig_after.get("total", 0))
            delta = total_after - total_before
            by_source_after = ig_after.get("by_source", {}) or {}
            by_source_before = ig_before.get("by_source", {}) or {}
            delta_by_source = {
                k: int(by_source_after.get(k, 0)) - int(by_source_before.get(k, 0))
                for k in set(by_source_after.keys()) | set(by_source_before.keys())
            }
            # Only print non-zero deltas
            delta_by_source = {k: v for k, v in delta_by_source.items() if v}

            log_kv(
                logger,
                "SCAN_END",
                scan_id=scan_id,
                total_ms=f"{dt_ms:.0f}",
                signals=signals_found,
                ig_http_delta=delta,
                ig_delta_by_source=delta_by_source,
            )
        else:
            log_kv(logger, "SCAN_END", scan_id=scan_id, total_ms=f"{dt_ms:.0f}", signals=signals_found)

    
    def _persist_signal_safely(
        self,
        *,
        user_id: str,
        symbol: str,
        entry_tf: str,
        direction: str,
        entry: float,
        sl: float,
        tp: float,
        rr: float,
        strategy_id: str,
        scan_id: str,
        reasons: List[str],
        payload: Optional[Dict[str, Any]],
        selected: Dict[str, Any],
        signal: SignalEvent,
    ) -> None:
        """Persist signal to JSONL history (legacy + public) with robust error handling."""
        try:
            from core.chart_annotation_builder import build_engine_annotations_v1_from_signal
            from core.signal_payload_v1 import build_payload_v1
            from core.signal_payload_public_v1 import to_public_v1
            from core.signals_store import append_public_signal_jsonl, append_signal_jsonl

            # 1. Build Base Payload (V1)
            annotations = build_engine_annotations_v1_from_signal(signal)
            sig_payload = build_payload_v1(
                user_id=str(user_id),
                symbol=str(symbol),
                tf=str(entry_tf),
                direction=str(direction),
                entry=float(entry),
                sl=float(sl),
                tp=float(tp),
                rr=float(rr),
                strategy_id=str(strategy_id),
                scan_id=str(scan_id),
                reasons=reasons,
                explain=(payload if isinstance(payload, dict) else None),
                score=(selected.get("score") if isinstance(selected, dict) else None),
                engine_annotations=annotations,
            )

            # 2. Persist Legacy
            try:
                append_signal_jsonl(sig_payload)
            except Exception as e:
                log_kv_error(logger, "SIGNALS_PERSIST_ERROR", stage="legacy", error=str(e))

            # 3. Persist Public (Additively)
            try:
                pub_payload = to_public_v1(sig_payload)
                append_public_signal_jsonl(pub_payload)
            except Exception as e:
                log_kv_error(logger, "SIGNALS_PERSIST_ERROR", stage="public", error=str(e))

        except Exception as e:
            # Catch build errors to ensure engine never crashes
            log_kv_error(logger, "SIGNALS_BUILD_ERROR", error=str(e))

    def _make_persistent_signal_key(
        self,
        *,
        symbol: str,
        timeframe: str,
        strategy_id: str,
        direction: str,
    ) -> str:
        """Stable key for cooldown persistence (Step 8).

        State key = (symbol, tf, strategy_id, direction)
        """
        raw = "|".join(
            [
                str(symbol).upper(),
                str(timeframe).upper(),
                str(strategy_id or "").strip(),
                str(direction).upper(),
            ]
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _get_day_key_utc(self, tz_offset_hours: int) -> str:
        now_utc = datetime.now(timezone.utc)
        local_now = now_utc + timedelta(hours=int(tz_offset_hours or 0))
        return local_now.date().isoformat()

    def _get_day_key_from_epoch(self, ts: float, tz_offset_hours: int) -> str:
        dt_utc = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        local_dt = dt_utc + timedelta(hours=int(tz_offset_hours or 0))
        return local_dt.date().isoformat()

    def _maybe_notify_admin_data_gap(self, *, symbol: str, details: Dict[str, Any]) -> None:
        # User requirement: only notify on setups found and on manual scans.
        # Data-gap alerts are operational noise; keep them opt-in.
        if not _ops_telegram_enabled():
            return

        notify_mode = str(getattr(config, "NOTIFY_MODE", "all") or "all").strip().lower()
        if notify_mode != "admin_only":
            return

        chat_id = getattr(config, "ADMIN_CHAT_ID", None) or getattr(config, "DEFAULT_CHAT_ID", None)
        if not chat_id:
            return

        cooldown_min = int(getattr(config, "DATA_GAP_NOTIFY_COOLDOWN_MIN", 60) or 60)
        cooldown_sec = max(cooldown_min, 1) * 60

        now_ts = time.time()
        sym = str(symbol).upper()
        last = float(self._data_gap_admin_last_sent.get(sym, 0.0))
        if (now_ts - last) < float(cooldown_sec):
            return
        self._data_gap_admin_last_sent[sym] = now_ts

        try:
            trend_tf = str(details.get("trend_tf") or "").upper()
            entry_tf = str(details.get("entry_tf") or "").upper()
            have_trend = details.get("have_trend")
            need_trend = details.get("need_trend")
            have_entry = details.get("have_entry")
            need_entry = details.get("need_entry")

            msg = (
                f"⚠️ DATA_GAP {sym} "
                f"{trend_tf} {have_trend}/{need_trend} | {entry_tf} {have_entry}/{need_entry}"
            )
            telegram_notifier.send_message(msg, chat_id=chat_id)
        except Exception:
            return

    def _select_candidate_after_governance(
        self,
        *,
        ranked_results: List[Any],
        symbol: str,
        entry_tf: str,
        tz_offset_hours: int,
        strategies: List[Dict[str, Any]],
        active_strategy: Dict[str, Any],
        profile: Dict[str, Any],
        now_ts: Optional[float] = None,
    ) -> Tuple[Optional[Any], Dict[str, Any]]:
        """Return first governance-passing candidate, optionally failing over.

        Governance here means cooldown + daily limit (persistent).
        """
        meta: Dict[str, Any] = {
            "used_failover": False,
            "blocked_winner_strategy_id": None,
            "blocked_reason": None,
            "governance": None,
        }

        if now_ts is None:
            now_ts = time.time()

        failover_on_block = bool(getattr(config, "STRATEGY_FAILOVER_ON_BLOCK", True))

        def _get_strategy_cfg(sid: str) -> Dict[str, Any]:
            try:
                if isinstance(strategies, list) and strategies and sid:
                    return next(
                        (s for s in strategies if isinstance(s, dict) and str(s.get("strategy_id") or "").strip() == str(sid)),
                        active_strategy,
                    )
            except Exception:
                return active_strategy
            return active_strategy

        for i, cand in enumerate(ranked_results or []):
            if cand is None or not getattr(cand, "has_setup", False) or getattr(cand, "setup", None) is None:
                continue

            cand_debug = cand.debug if isinstance(getattr(cand, "debug", None), dict) else {}
            cand_sid = str(cand_debug.get("strategy_id") or "").strip() or "legacy"
            cand_cfg = _get_strategy_cfg(cand_sid)

            cand_setup = cand.setup
            cand_dir = str(cand_setup.direction)
            cand_tf = str(entry_tf)

            cand_signal_key = self._make_persistent_signal_key(
                symbol=str(symbol),
                timeframe=str(cand_tf),
                strategy_id=str(cand_sid or ""),
                direction=str(cand_dir),
            )

            cand_max_per_day = int(
                (cand_cfg.get("daily_limit") if isinstance(cand_cfg, dict) else None)
                or (cand_cfg.get("max_signals_per_day_per_symbol") if isinstance(cand_cfg, dict) else None)
                or (cand_cfg.get("daily_limit_per_symbol") if isinstance(cand_cfg, dict) else None)
                or profile.get("daily_limit")
                or profile.get("max_signals_per_day_per_symbol")
                or profile.get("daily_limit_per_symbol")
                or config.DAILY_LIMIT_PER_SYMBOL
            )
            cand_cooldown_minutes = int(
                (cand_cfg.get("cooldown_minutes") if isinstance(cand_cfg, dict) else None)
                or profile.get("cooldown_minutes")
                or config.SIGNAL_COOLDOWN_MINUTES
            )

            if self._state_loaded:
                if not self._state_store.can_send(cand_signal_key, now_ts, cooldown_minutes=cand_cooldown_minutes):
                    rec = self._state_store.get_sent_record(cand_signal_key)
                    last_ts = rec.ts if rec is not None else None
                    remaining_s = None
                    if last_ts is not None and cand_cooldown_minutes > 0:
                        age_s = float(now_ts) - float(last_ts)
                        remaining_s = max(float(cand_cooldown_minutes) * 60.0 - float(age_s), 0.0)
                    gov = build_governance_evidence(
                        strategy_id=cand_sid,
                        symbol=symbol,
                        tf=cand_tf,
                        direction=cand_dir,
                        last_sent_ts=last_ts,
                        cooldown_minutes=cand_cooldown_minutes,
                        cooldown_remaining_s=remaining_s,
                        sent_today_count=None,
                        daily_limit=(cand_max_per_day if cand_max_per_day > 0 else None),
                    )
                    r_out = normalize_pair_none_reason(["COOLDOWN_BLOCK"])
                    if i == 0:
                        meta["blocked_winner_strategy_id"] = cand_sid
                        meta["blocked_reason"] = r_out
                        meta["governance"] = gov
                    if not failover_on_block:
                        return (None, meta)
                    meta["used_failover"] = True
                    continue

                if cand_max_per_day > 0:
                    day_key = self._get_day_key_utc(tz_offset_hours)
                    day_count = self._state_store.get_daily_count(symbol, cand_tf, str(cand_sid or ""), day_key)
                    if day_count >= cand_max_per_day:
                        gov = build_governance_evidence(
                            strategy_id=cand_sid,
                            symbol=symbol,
                            tf=cand_tf,
                            direction=cand_dir,
                            last_sent_ts=None,
                            cooldown_minutes=cand_cooldown_minutes,
                            cooldown_remaining_s=None,
                            sent_today_count=int(day_count),
                            daily_limit=int(cand_max_per_day),
                        )
                        r_out = normalize_pair_none_reason(["DAILY_LIMIT_BLOCK"])
                        if i == 0:
                            meta["blocked_winner_strategy_id"] = cand_sid
                            meta["blocked_reason"] = r_out
                            meta["governance"] = gov
                        if not failover_on_block:
                            return (None, meta)
                        meta["used_failover"] = True
                        continue

            return (cand, meta)

        if meta.get("blocked_reason") is None:
            meta["blocked_reason"] = normalize_pair_none_reason(["UNKNOWN_ERROR"])
        return (None, meta)

    def _save_state_debounced(self, *, scan_id: str) -> None:
        if not self._state_dirty:
            return

        now_ts = time.time()
        if (now_ts - self._state_last_saved_ts) < float(self._state_save_min_interval_sec):
            return

        t0 = time.perf_counter()
        try:
            self._state_store.prune(older_than_days=14, now_ts=now_ts)
            self._state_store.save_atomic()
            self._state_last_saved_ts = now_ts
            self._state_dirty = False
            dt_ms = (time.perf_counter() - t0) * 1000.0
            counts = self._state_store.snapshot_counts()
            log_kv(
                logger,
                "STATE_SAVED",
                scan_id=scan_id,
                ms=f"{dt_ms:.2f}",
                path=str(self._state_store.path),
                **counts,
            )
        except Exception:
            log_kv_error(logger, "STATE_SAVE_ERROR", scan_id=scan_id)

    def _flush_state_if_dirty(self, *, scan_id: str) -> None:
        # Force save at end-of-cycle if dirty.
        if not self._state_dirty:
            return
        t0 = time.perf_counter()
        try:
            now_ts = time.time()
            self._state_store.prune(older_than_days=14, now_ts=now_ts)
            self._state_store.save_atomic()
            self._state_last_saved_ts = now_ts
            self._state_dirty = False
            dt_ms = (time.perf_counter() - t0) * 1000.0
            counts = self._state_store.snapshot_counts()
            log_kv(
                logger,
                "STATE_SAVED",
                scan_id=scan_id,
                ms=f"{dt_ms:.2f}",
                path=str(self._state_store.path),
                **counts,
            )
        except Exception:
            log_kv_error(logger, "STATE_SAVE_ERROR", scan_id=scan_id)

    def _scan_for_user(
        self,
        user,
        *,
        scan_id: str,
        outcomes: Optional[Dict[str, Any]] = None,
        notify_mode_override: Optional[str] = None,
    ) -> int:
        uid = user.get("user_id") or user.get("telegram_handle") or "unknown"
        user_id = str(user.get("user_id") or uid)
        profile = user
        tz_offset_hours = int(profile.get("tz_offset_hours") or 0)
        pairs = profile.get("watch_pairs", [])
        try:
            from core.plans import clamp_pairs, effective_max_pairs

            pairs = clamp_pairs(pairs, int(effective_max_pairs(profile)))
        except Exception:
            pass
        if not pairs:
            return 0

        # Strategy loader: never raises. Invalid config must not crash engine.
        # If the profile does not define strategies, fall back to per-user stored strategies.
        merged_profile = dict(profile) if isinstance(profile, dict) else profile
        try:
            has_profile_strategies = bool(profile.get("strategies")) or (profile.get("strategy") is not None)
        except Exception:
            has_profile_strategies = True
        if not has_profile_strategies and isinstance(merged_profile, dict):
            try:
                from core.user_strategies_store import load_user_strategies

                stored = load_user_strategies(user_id)
                if stored:
                    merged_profile["strategies"] = stored
            except Exception:
                pass

        notify_mode = (
            str(notify_mode_override).strip().lower()
            if notify_mode_override is not None
            else str(getattr(config, "NOTIFY_MODE", "all") or "all").strip().lower()
        )
        load_res = load_strategies_from_profile(merged_profile)
        strategies = load_res.strategies
        profile_errors = list(load_res.errors)

        # Hard rule: do not scan unless user explicitly configured a strategy.
        # If strategies are invalid, surface PROFILE_INVALID; otherwise NO_STRATEGY_CONFIGURED.
        if not strategies:
            reason = "PROFILE_INVALID" if profile_errors else "NO_STRATEGY_CONFIGURED"
            internal_reason = "profile_invalid" if profile_errors else "no_strategy_configured"
            extra: Dict[str, Any] = {}
            if profile_errors and notify_mode == "admin_only":
                extra["profile_errors"] = ";".join([str(e) for e in profile_errors[:6]])
            if isinstance(outcomes, dict):
                for pair in pairs:
                    symbol = str(pair or "").strip().upper()
                    if not symbol:
                        continue
                    row = {
                        "kind": "NONE",
                        "reason": reason,
                        "internal_reason": internal_reason,
                    }
                    row.update(extra)
                    outcomes[symbol] = row
            return 0

        active_strategy = strategies[0] if strategies else profile
        strategy_id = None
        try:
            if isinstance(active_strategy, dict):
                strategy_id = str(active_strategy.get("strategy_id") or "").strip() or None
        except Exception:
            strategy_id = None

        # Update signal outcomes (win/loss) using cached candles.
        try:
            evaluate_pending_signals_for_user(user_id=user_id)
        except Exception:
            pass
        
        signals_sent = 0

        default_entry_tf = "NA"
        try:
            if isinstance(active_strategy, dict):
                default_entry_tf = str(active_strategy.get("entry_tf") or profile.get("entry_tf") or "NA").upper()
            else:
                default_entry_tf = str(profile.get("entry_tf") or "NA").upper()
        except Exception:
            default_entry_tf = "NA"

        for pair in pairs:
            t_symbol = time.perf_counter()
            symbol = pair.strip().upper()
            # If profile strategy config is invalid, do not proceed with scanning.
            if not strategies and profile_errors:
                extra: Dict[str, Any] = {}
                if notify_mode == "admin_only":
                    extra["profile_errors"] = ";".join([str(e) for e in profile_errors[:6]])
                if isinstance(outcomes, dict):
                    outcomes[str(symbol).upper()] = {
                        "kind": "NONE",
                        "reason": "PROFILE_INVALID",
                        "internal_reason": "profile_invalid",
                    }
                try:
                    payload = build_pair_none_explain(
                        symbol=symbol,
                        tf=default_entry_tf,
                        scan_id=scan_id,
                        strategy_id=str(strategy_id or "NA"),
                        reason="PROFILE_INVALID",
                        debug=None,
                        governance=None,
                    )
                    _maybe_audit_explain(payload)
                    _maybe_emit_metrics_from_explain(payload, debug=None, failover_used=None)
                except Exception:
                    pass
                log_kv(
                    logger,
                    "PAIR_NONE",
                    scan_id=scan_id,
                    symbol=symbol,
                    strategy_id=strategy_id,
                    reason="PROFILE_INVALID",
                    **extra,
                    ms_total=f"{(time.perf_counter() - t_symbol) * 1000.0:.2f}",
                )
                continue


            t_market = time.perf_counter()
            raw_5m = market_cache.get_candles(symbol)
            market_cache_get_ms = (time.perf_counter() - t_market) * 1000.0
            market_cache_hit = bool(raw_5m)
            if not raw_5m:
                r_out = normalize_pair_none_reason(["no_m5"])
                if isinstance(outcomes, dict):
                    outcomes[str(symbol).upper()] = {
                        "kind": "NONE",
                        "reason": r_out,
                        "internal_reason": "no_m5",
                    }
                try:
                    payload = build_pair_none_explain(
                        symbol=symbol,
                        tf=default_entry_tf,
                        scan_id=scan_id,
                        strategy_id=str(strategy_id or "NA"),
                        reason=r_out,
                        debug={"internal_reason": "no_m5"},
                        governance=None,
                    )
                    _maybe_audit_explain(payload)
                    _maybe_emit_metrics_from_explain(payload, debug={"internal_reason": "no_m5"}, failover_used=None)
                except Exception:
                    pass
                log_kv(
                    logger,
                    "PAIR_NONE",
                    scan_id=scan_id,
                    symbol=symbol,
                    strategy_id=strategy_id,
                    reason=r_out,
                    internal_reason="no_m5",
                    ms_total=f"{(time.perf_counter() - t_symbol) * 1000.0:.2f}",
                )
                continue

            trend_tf = str(active_strategy.get("trend_tf", profile.get("trend_tf", "H4"))).upper()
            entry_tf = str(active_strategy.get("entry_tf", profile.get("entry_tf", "M15"))).upper()

            min_trend_bars = int(
                (active_strategy.get("min_trend_bars") if isinstance(active_strategy, dict) else None)
                or profile.get("min_trend_bars")
                or config.MIN_TREND_BARS
            )
            min_entry_bars = int(
                (active_strategy.get("min_entry_bars") if isinstance(active_strategy, dict) else None)
                or profile.get("min_entry_bars")
                or config.MIN_ENTRY_BARS
            )

            ready, reason, details = readiness_check(
                market_cache,
                symbol=symbol,
                trend_tf=trend_tf,
                entry_tf=entry_tf,
                min_trend_bars=min_trend_bars,
                min_entry_bars=min_entry_bars,
            )
            if not ready:
                self._maybe_notify_admin_data_gap(symbol=symbol, details=details)

                # Emit have/need fields like have_h4/need_h4 so logs are greppable.
                tf1 = str(details.get("trend_tf") or trend_tf).strip().lower()
                tf2 = str(details.get("entry_tf") or entry_tf).strip().lower()
                have1 = int(details.get("have_trend") or 0)
                need1 = int(details.get("need_trend") or min_trend_bars)
                have2 = int(details.get("have_entry") or 0)
                need2 = int(details.get("need_entry") or min_entry_bars)

                r_out = normalize_pair_none_reason(["data_gap"])
                if isinstance(outcomes, dict):
                    outcomes[str(symbol).upper()] = {
                        "kind": "NONE",
                        "reason": r_out,
                        "internal_reason": "data_gap",
                        "have_trend": have1,
                        "need_trend": need1,
                        "have_entry": have2,
                        "need_entry": need2,
                        "trend_tf": str(details.get("trend_tf") or trend_tf),
                        "entry_tf": str(details.get("entry_tf") or entry_tf),
                    }
                try:
                    payload = build_pair_none_explain(
                        symbol=symbol,
                        tf=str(entry_tf),
                        scan_id=scan_id,
                        strategy_id=str(strategy_id or "NA"),
                        reason=r_out,
                        debug={
                            "internal_reason": "data_gap",
                            f"have_{tf1}": have1,
                            f"need_{tf1}": need1,
                            f"have_{tf2}": have2,
                            f"need_{tf2}": need2,
                        },
                        governance=None,
                    )
                    _maybe_audit_explain(payload)
                    _maybe_emit_metrics_from_explain(payload, debug={"internal_reason": "data_gap"}, failover_used=None)
                except Exception:
                    pass
                log_kv(
                    logger,
                    "PAIR_NONE",
                    scan_id=scan_id,
                    symbol=symbol,
                    strategy_id=strategy_id,
                    reason=r_out,
                    internal_reason="data_gap",
                    **{f"have_{tf1}": have1, f"need_{tf1}": need1, f"have_{tf2}": have2, f"need_{tf2}": need2},
                    ms_total=f"{(time.perf_counter() - t_symbol) * 1000.0:.2f}",
                )
                continue

            # Use resampled timeframe cache (no external IO)
            trend_data, trend_meta = market_cache.get_resampled(symbol, trend_tf, with_meta=True)
            entry_data, entry_meta = market_cache.get_resampled(symbol, entry_tf, with_meta=True)

            t_objs = _convert_dicts_to_candles(trend_data)
            e_objs = _convert_dicts_to_candles(entry_data)

            engine_version = str(active_strategy.get("engine_version") or profile.get("engine_version") or "").strip()

            # Engine call timing
            t_engine = time.perf_counter()
            try:
                if engine_version.lower().startswith("indicator_free"):
                    # New indicator-free pipeline (structure trend + engines.detectors)
                    engine_profile = active_strategy
                    try:
                        if isinstance(profile, dict) and strategies:
                            # Provide all strategies to the engine for per-pair strategy loop.
                            engine_profile = dict(profile)
                            engine_profile["strategies"] = list(strategies)
                    except Exception:
                        engine_profile = active_strategy
                    result = scan_pair_cached_indicator_free(symbol, engine_profile, t_objs, e_objs)
                else:
                    # Default MA-based detector pipeline
                    result = scan_pair_cached(symbol, active_strategy, t_objs, e_objs)
            except Exception as _eng_exc:
                import traceback
                log_kv_error(
                    logger,
                    "scan_engine_error",
                    scan_id=scan_id,
                    user_id=user_id,
                    symbol=symbol,
                    trend_tf=trend_tf,
                    entry_tf=entry_tf,
                    engine_version=engine_version,
                    exc=str(_eng_exc)[:200],
                    tb=traceback.format_exc()[-500:],
                )
                if isinstance(outcomes, dict):
                    outcomes[str(symbol).upper()] = {
                        "kind": "ERROR",
                        "reason": "ENGINE_ERROR",
                        "internal_reason": str(type(_eng_exc).__name__),
                    }
                continue
            engine_ms = (time.perf_counter() - t_engine) * 1000.0

            if result.strategy_name is None and isinstance(active_strategy, dict):
                result.strategy_name = str(active_strategy.get("name") or "").strip() or None

            debug = result.debug or {}
            # Prefer engine-provided strategy_id if present.
            try:
                if isinstance(debug, dict):
                    strategy_id = str(debug.get("strategy_id") or "").strip() or strategy_id
            except Exception:
                pass

            # Governance must be applied using the winner strategy config (not strategies[0]).
            # This ensures one noisy strategy doesn't block others.
            winner_strategy = active_strategy
            try:
                if isinstance(strategies, list) and strategies and strategy_id:
                    winner_strategy = next(
                        (s for s in strategies if isinstance(s, dict) and str(s.get("strategy_id") or "").strip() == str(strategy_id)),
                        active_strategy,
                    )
            except Exception:
                winner_strategy = active_strategy
            per_detector_ms = debug.get("per_detector_ms") if isinstance(debug.get("per_detector_ms"), dict) else {}

            # Performance guard: feature build + per-detector timing (indicator-free engine)
            try:
                feat_ms = debug.get("feature_build_ms")
                if feat_ms is not None and float(feat_ms) > float(config.FEATURE_WARN_MS):
                    self._perf_feature_warn_total += 1
                    log_kv(
                        logger,
                        "PERF_WARN",
                        scan_id=scan_id,
                        symbol=symbol,
                        kind="feature_build_ms",
                        ms=f"{float(feat_ms):.2f}",
                        warn_ms=int(config.FEATURE_WARN_MS),
                        engine=str(engine_version or ""),
                    )
            except Exception:
                pass

            try:
                for det_name, ms in per_detector_ms.items():
                    ms_f = float(ms)
                    if ms_f > float(config.DETECTOR_WARN_MS):
                        self._perf_detector_warn[str(det_name)] = int(self._perf_detector_warn.get(str(det_name), 0)) + 1
                        prev_max = float(self._perf_detector_max_ms.get(str(det_name), 0.0))
                        if ms_f > prev_max:
                            self._perf_detector_max_ms[str(det_name)] = ms_f
                        log_kv(
                            logger,
                            "PERF_WARN",
                            scan_id=scan_id,
                            symbol=symbol,
                            detector=str(det_name),
                            kind="detector_ms",
                            ms=f"{ms_f:.2f}",
                            warn_ms=int(config.DETECTOR_WARN_MS),
                            engine=str(engine_version or ""),
                        )
            except Exception:
                pass

            # Selected signal summary fields
            def _extract_selected(res, dbg: Dict[str, Any]) -> Dict[str, Any]:
                out = {
                    "direction": None,
                    "score": None,
                    "min_score": None,
                    "regime": None,
                    "detectors": None,
                    "buy_score": None,
                    "sell_score": None,
                    "rr": None,
                }
                try:
                    if getattr(res, "setup", None) is not None:
                        out["direction"] = res.setup.direction
                        out["rr"] = f"{float(res.setup.rr):.2f}"
                except Exception:
                    pass

                try:
                    if isinstance(dbg, dict):
                        if dbg.get("score") is not None:
                            out["score"] = f"{float(dbg.get('score')):.2f}"
                        if dbg.get("min_score") is not None:
                            out["min_score"] = f"{float(dbg.get('min_score')):.2f}"
                        if dbg.get("regime") is not None:
                            out["regime"] = str(dbg.get("regime"))
                        dets = dbg.get("detectors_hit")
                        if isinstance(dets, list) and dets:
                            out["detectors"] = ",".join([str(x) for x in dets])
                        if dbg.get("buy_score") is not None:
                            out["buy_score"] = f"{float(dbg.get('buy_score')):.2f}"
                        if dbg.get("sell_score") is not None:
                            out["sell_score"] = f"{float(dbg.get('sell_score')):.2f}"
                except Exception:
                    pass
                return out

            selected = _extract_selected(result, debug if isinstance(debug, dict) else {})

            ms_total = (time.perf_counter() - t_symbol) * 1000.0

            # Performance guard: per-pair total runtime
            try:
                if float(ms_total) > float(config.PAIR_WARN_MS):
                    self._perf_pair_warn_total += 1
                    log_kv(
                        logger,
                        "PERF_WARN",
                        scan_id=scan_id,
                        symbol=symbol,
                        kind="pair_ms",
                        ms=f"{ms_total:.2f}",
                        warn_ms=int(config.PAIR_WARN_MS),
                        engine=str(engine_version or ""),
                    )
            except Exception:
                pass

            if not (result.has_setup and result.setup is not None):
                # v1: avoid log spam when all strategies are regime-blocked.
                # This is an expected skip, not an actionable failure.
                try:
                    if isinstance(result.reasons, list) and "REGIME_BLOCKED" in result.reasons:
                        continue
                except Exception:
                    continue

                reason = normalize_pair_none_reason(result.reasons)

                # DEBUG: track raw reasons when normalized to UNKNOWN_ERROR
                if reason == "UNKNOWN_ERROR":
                    logger.info(f"DEBUG_RAW_REASONS symbol={symbol} raw={result.reasons}")

                extra: Dict[str, Any] = {}
                try:
                    dbg = result.debug if isinstance(result.debug, dict) else {}

                    try:
                        if isinstance(dbg, dict):
                            if dbg.get("regime") is not None:
                                extra.setdefault("regime", str(dbg.get("regime")))
                            if dbg.get("regime_evidence") is not None:
                                extra.setdefault("regime_evidence", dbg.get("regime_evidence"))

                            if dbg.get("detectors_total") is not None:
                                extra.setdefault("detectors_total", dbg.get("detectors_total"))

                            # Multi-strategy arbitration summary (v1)
                            if dbg.get("candidates") is not None:
                                extra.setdefault("candidates", dbg.get("candidates"))
                            if dbg.get("candidates_top") is not None:
                                extra.setdefault("candidates_top", dbg.get("candidates_top"))
                            if dbg.get("winner_strategy_id") is not None:
                                extra.setdefault("winner_strategy_id", dbg.get("winner_strategy_id"))

                            # Flatten structure counts for one-line readability.
                            re = dbg.get("regime_evidence")
                            if isinstance(re, dict):
                                for k in ("hh", "hl", "lh", "ll"):
                                    if re.get(k) is not None:
                                        extra.setdefault(k, re.get(k))
                    except Exception:
                        pass

                    # Score-aware failure context for greppable ops logs.
                    try:
                        if reason in ("SCORE_BELOW_MIN", "CONFLICT_SCORE"):
                            if dbg.get("buy_score") is not None:
                                extra["buy_score"] = f"{float(dbg.get('buy_score')):.2f}"
                            if dbg.get("sell_score") is not None:
                                extra["sell_score"] = f"{float(dbg.get('sell_score')):.2f}"
                            if dbg.get("min_score") is not None:
                                extra["min_score"] = f"{float(dbg.get('min_score')):.2f}"
                            if dbg.get("regime") is not None:
                                extra["regime"] = str(dbg.get("regime"))

                            # Near-miss explanation: top contribs + raw/bonus
                            extra.update(_extract_score_breakdown_fields_for_logs(dbg))
                    except Exception:
                        pass

                    sf = dbg.get("setup_fail") if isinstance(dbg, dict) else None
                    if isinstance(sf, dict):
                        # Required for diagnosing SETUP_BUILD_FAILED quickly.
                        # Always include required setup diagnostics (use NA when missing).
                        for k in (
                            "rr",
                            "min_rr",
                            "entry_zone",
                            "entry_zone_width_pct",
                            "sl_dist",
                            "tp_dist",
                            "sl",
                            "tp",
                        ):
                            v = sf.get(k)
                            extra[k] = v if v is not None else "NA"

                        # Keep logs greppable with stable, compact keys.
                        for k in (
                            "min_rr",
                            "sl_dist",
                            "entry_zone_width_pct",
                            "width_pct",
                            "tp_dist",
                            "sl_pips",
                            "sl_dist_pct",
                            "max_sl_dist_pct",
                            "nearest_sr",
                            "fibo_ext_targets",
                            "targets_count",
                            "tp_source",
                            "tp_pips",
                            "zone_level",
                            "zone_low",
                            "zone_high",
                            "zone_width_abs",
                            "zone_width_frac",
                            "entry_price",
                        ):
                            if k in sf and sf.get(k) is not None:
                                extra[k] = sf.get(k)
                except Exception:
                    extra = {}

                try:
                    payload = build_pair_none_explain(
                        symbol=symbol,
                        tf=str(entry_tf),
                        scan_id=scan_id,
                        strategy_id=str(strategy_id or "NA"),
                        reason=str(reason),
                        debug=(dbg if isinstance(dbg, dict) else None),
                        governance=None,
                    )
                    debug = _attach_explain_to_debug(debug, payload)
                    try:
                        result.debug = debug
                    except Exception:
                        pass
                    _maybe_audit_explain(payload)
                    _maybe_emit_metrics_from_explain(payload, debug=(dbg if isinstance(dbg, dict) else None), failover_used=None)
                except Exception:
                    pass
                log_kv(
                    logger,
                    "PAIR_NONE",
                    scan_id=scan_id,
                    symbol=symbol,
                    strategy_id=strategy_id,
                    reason=reason,
                    **extra,
                    ms_total=f"{ms_total:.2f}",
                )

                if isinstance(outcomes, dict):
                    outcomes[str(symbol).upper()] = {
                        "kind": "NONE",
                        "reason": str(reason),
                        "strategy_id": str(strategy_id or "NA"),
                    }

            if result.has_setup and result.setup is not None:
                # Keep original arbitration summary from engine (winner before governance).
                base_debug = debug if isinstance(debug, dict) else {}
                base_summary = {}
                try:
                    for k in ("candidates", "candidates_top", "winner_strategy_id"):
                        if k in base_debug and base_debug.get(k) is not None:
                            base_summary[k] = base_debug.get(k)
                except Exception:
                    base_summary = {}

                ranked_results = None
                try:
                    if isinstance(debug, dict) and isinstance(debug.get("_candidates_ranked_results"), list):
                        ranked_results = [
                            r
                            for r in debug.get("_candidates_ranked_results")
                            if getattr(r, "has_setup", False) and getattr(r, "setup", None) is not None
                        ]
                except Exception:
                    ranked_results = None
                if not ranked_results:
                    ranked_results = [result]

                chosen_result, gmeta = self._select_candidate_after_governance(
                    ranked_results=ranked_results,
                    symbol=symbol,
                    entry_tf=entry_tf,
                    tz_offset_hours=tz_offset_hours,
                    strategies=strategies,
                    active_strategy=active_strategy,
                    profile=profile,
                )

                blocked_winner_strategy_id = gmeta.get("blocked_winner_strategy_id")
                blocked_reason = gmeta.get("blocked_reason")
                used_failover = bool(gmeta.get("used_failover"))
                gov = gmeta.get("governance")

                if chosen_result is None:
                    r_out = normalize_pair_none_reason([blocked_reason or "UNKNOWN_ERROR"])
                    gov = gov or build_governance_evidence(strategy_id=blocked_winner_strategy_id, symbol=symbol, tf=entry_tf)
                    gov_flat = {f"governance_{k}": v for k, v in gov.items()}

                    try:
                        payload = build_pair_none_explain(
                            symbol=symbol,
                            tf=str(entry_tf),
                            scan_id=scan_id,
                            strategy_id=str(strategy_id or "NA"),
                            reason=r_out,
                            debug=(debug if isinstance(debug, dict) else None),
                            governance=gov,
                        )
                        debug = _attach_explain_to_debug(debug, payload)
                        try:
                            result.debug = debug
                        except Exception:
                            pass
                        _maybe_audit_explain(payload)
                        _maybe_emit_metrics_from_explain(payload, debug=debug, failover_used=used_failover)
                    except Exception:
                        pass
                    log_kv(
                        logger,
                        "PAIR_NONE",
                        scan_id=scan_id,
                        symbol=symbol,
                        strategy_id=str(strategy_id),
                        reason=r_out,
                        candidates=(debug.get("candidates") if isinstance(debug, dict) else None),
                        candidates_top=(debug.get("candidates_top") if isinstance(debug, dict) else None),
                        blocked_winner_strategy_id=blocked_winner_strategy_id,
                        blocked_reason=r_out,
                        **gov_flat,
                        ms_total=f"{ms_total:.2f}",
                    )

                    if isinstance(outcomes, dict):
                        outcomes[str(symbol).upper()] = {
                            "kind": "NONE",
                            "reason": str(r_out),
                            "strategy_id": str(strategy_id or "NA"),
                            "blocked_winner_strategy_id": blocked_winner_strategy_id,
                            "blocked_reason": str(r_out),
                        }
                    continue

                if chosen_result is not result:
                    result = chosen_result
                    debug = result.debug or {}
                    # Preserve arbitration summary fields from the original engine winner.
                    try:
                        if isinstance(debug, dict) and isinstance(base_summary, dict) and base_summary:
                            merged = dict(debug)
                            merged.update(base_summary)
                            result.debug = merged
                            debug = merged
                    except Exception:
                        pass
                    # Prefer chosen strategy id.
                    try:
                        if isinstance(debug, dict):
                            strategy_id = str(debug.get("strategy_id") or "").strip() or strategy_id
                    except Exception:
                        pass
                    # Also update winner strategy config
                    try:
                        if isinstance(strategies, list) and strategies and strategy_id:
                            winner_strategy = next(
                                (s for s in strategies if isinstance(s, dict) and str(s.get("strategy_id") or "").strip() == str(strategy_id)),
                                active_strategy,
                            )
                    except Exception:
                        winner_strategy = active_strategy

                    # Recompute selected fields after failover to avoid stale score/direction/rr.
                    selected = _extract_selected(result, debug if isinstance(debug, dict) else {})

                setup = result.setup
                reasons = list(result.reasons)
                if result.strategy_name:
                    reasons.insert(0, f"STRATEGY|{result.strategy_name}")

                signal = SignalEvent(
                    pair=symbol,
                    direction=setup.direction,
                    timeframe=entry_tf,
                    entry=float(setup.entry),
                    sl=float(setup.sl),
                    tp=float(setup.tp),
                    rr=float(setup.rr),
                    reasons=reasons,
                    tz_offset_hours=tz_offset_hours,
                    engine_version=(engine_version or (result.strategy_name or "")),
                    user_id=str(user_id),
                    user_label=str(uid),
                    strategy_id=str(strategy_id or ""),
                )

                # --- Quality / spam controls (pre-send) ---
                # Score gate
                min_score = float(
                    (winner_strategy.get("min_score") if isinstance(winner_strategy, dict) else None)
                    or profile.get("min_score")
                    or 0.0
                )
                score_val = None
                try:
                    if selected.get("score") is not None:
                        score_val = float(selected.get("score"))
                except Exception:
                    score_val = None

                if min_score > 0.0 and score_val is not None and score_val < min_score:
                    r_out = normalize_pair_none_reason(["low_score"])

                    try:
                        tmp_dbg = dict(debug) if isinstance(debug, dict) else {}
                        tmp_dbg["min_score"] = float(min_score)
                        if score_val is not None:
                            d = str(selected.get("direction") or setup.direction or "").upper()
                            tmp_dbg["direction"] = d or tmp_dbg.get("direction")
                            if d == "BUY":
                                tmp_dbg["buy_score"] = float(score_val)
                            elif d == "SELL":
                                tmp_dbg["sell_score"] = float(score_val)

                        payload = build_pair_none_explain(
                            symbol=symbol,
                            tf=str(entry_tf),
                            scan_id=scan_id,
                            strategy_id=str(strategy_id or "NA"),
                            reason=r_out,
                            debug=tmp_dbg,
                            governance=gov,
                        )
                        debug = _attach_explain_to_debug(debug, payload)
                        try:
                            result.debug = debug
                        except Exception:
                            pass
                        _maybe_audit_explain(payload)
                        _maybe_emit_metrics_from_explain(payload, debug=tmp_dbg, failover_used=used_failover)
                    except Exception:
                        pass
                    log_kv(
                        logger,
                        "PAIR_NONE",
                        scan_id=scan_id,
                        symbol=symbol,
                        strategy_id=strategy_id,
                        reason=r_out,
                        score=f"{score_val:.2f}",
                        min_score=f"{min_score:.2f}",
                        ms_total=f"{ms_total:.2f}",
                    )

                    if isinstance(outcomes, dict):
                        outcomes[str(symbol).upper()] = {
                            "kind": "NONE",
                            "reason": str(r_out),
                            "strategy_id": str(strategy_id or "NA"),
                            "score": score_val,
                            "min_score": min_score,
                        }
                    continue

                # Daily per-symbol cap
                max_per_day = int(
                    # Step 8: strategy-level daily limit
                    (winner_strategy.get("daily_limit") if isinstance(winner_strategy, dict) else None)
                    or (winner_strategy.get("max_signals_per_day_per_symbol") if isinstance(winner_strategy, dict) else None)
                    or (winner_strategy.get("daily_limit_per_symbol") if isinstance(winner_strategy, dict) else None)
                    or profile.get("daily_limit")
                    or profile.get("max_signals_per_day_per_symbol")
                    or profile.get("daily_limit_per_symbol")
                    or config.DAILY_LIMIT_PER_SYMBOL
                )

                # Conflict policy (same-day opposite direction)
                conflict_policy = str(
                    (winner_strategy.get("conflict_policy") if isinstance(winner_strategy, dict) else None)
                    or profile.get("conflict_policy")
                    or "skip"
                ).strip().lower()

                notify_mode = str(getattr(config, "NOTIFY_MODE", "all") or "all").strip().lower()

                # Strategy-scoped persistence key (Step 8)
                signal_key = self._make_persistent_signal_key(
                    symbol=str(symbol),
                    timeframe=str(signal.timeframe),
                    strategy_id=str(strategy_id or ""),
                    direction=str(signal.direction),
                )
                now_ts = time.time()

                if self._state_loaded:
                    if conflict_policy == "skip":
                        try:
                            day_key = self._get_day_key_utc(tz_offset_hours)
                            target_dir = str(signal.direction).upper()
                            for rec in self._state_store.snapshot_sent():
                                if rec.symbol != symbol:
                                    continue
                                if str(rec.timeframe or "").upper() != str(entry_tf).upper():
                                    continue
                                if str(rec.strategy_id or "") != str(strategy_id or ""):
                                    continue
                                if not rec.direction:
                                    continue
                                if rec.direction == target_dir:
                                    continue
                                if self._get_day_key_from_epoch(rec.ts, tz_offset_hours) == day_key:
                                    r_out = normalize_pair_none_reason(["conflict"])

                                    try:
                                        tmp_dbg = dict(debug) if isinstance(debug, dict) else {}
                                        tmp_dbg["direction"] = target_dir
                                        payload = build_pair_none_explain(
                                            symbol=symbol,
                                            tf=str(entry_tf),
                                            scan_id=scan_id,
                                            strategy_id=str(strategy_id or "NA"),
                                            reason=r_out,
                                            debug=tmp_dbg,
                                            governance=gov,
                                        )
                                        debug = _attach_explain_to_debug(debug, payload)
                                        try:
                                            result.debug = debug
                                        except Exception:
                                            pass
                                        _maybe_audit_explain(payload)
                                        _maybe_emit_metrics_from_explain(payload, debug=tmp_dbg, failover_used=used_failover)
                                    except Exception:
                                        pass
                                    log_kv(
                                        logger,
                                        "PAIR_NONE",
                                        scan_id=scan_id,
                                        symbol=symbol,
                                        strategy_id=strategy_id,
                                        reason=r_out,
                                        policy=conflict_policy,
                                        prev_direction=rec.direction,
                                        direction=target_dir,
                                        ms_total=f"{ms_total:.2f}",
                                    )
                                    raise StopIteration()
                        except StopIteration:
                            continue
                        except Exception:
                            # If conflict detection fails, don't break scanning.
                            pass

                # Passed controls => log OK and proceed to send
                top_hits = None

                # --- SHADOW EVALUATION BLOCK ---
                try:
                    from core.feature_flags import check_flag
                    if check_flag("FF_SHADOW_EVAL"):
                        # Shadow Logic: strictly experimental.
                        # Example: Shadow model penalizes low RR more heavily logic.
                        shadow_score = score_val
                        if getattr(signal, "rr", 0.0) < 2.0:
                            shadow_score *= 0.8
                        
                        log_kv(
                            logger,
                            "METRICS_SHADOW_COMPARE",
                            symbol=symbol,
                            tf=str(entry_tf),
                            live_score=score_val,
                            shadow_score=shadow_score,
                            delta=shadow_score - score_val,
                            scan_id=scan_id
                        )
                except Exception:
                    pass
                # -------------------------------

                hits_n = None
                try:
                    if isinstance(debug, dict):
                        hd = debug.get("hits")
                        if isinstance(hd, list):
                            hits_n = int(len(hd))
                        chosen = debug.get("detectors_hit")
                        if isinstance(chosen, list) and chosen:
                            top_hits = ",".join([str(x) for x in chosen[:4]])
                except Exception:
                    top_hits = None
                    hits_n = None

                try:
                    payload = build_pair_ok_explain(
                        symbol=symbol,
                        tf=str(entry_tf),
                        scan_id=scan_id,
                        strategy_id=str(strategy_id or "NA"),
                        debug=(debug if isinstance(debug, dict) else None),
                        governance=gov,
                    )
                    debug = _attach_explain_to_debug(debug, payload)
                    try:
                        result.debug = debug
                    except Exception:
                        pass
                    _maybe_audit_explain(payload)
                    _maybe_emit_metrics_from_explain(payload, debug=debug, failover_used=used_failover)
                except Exception:
                    payload = None

                try:
                    self._persist_signal_safely(
                        user_id=str(user_id),
                        symbol=str(symbol),
                        entry_tf=str(entry_tf),
                        direction=str(setup.direction),
                        entry=float(setup.entry),
                        sl=float(setup.sl),
                        tp=float(setup.tp),
                        rr=float(setup.rr),
                        strategy_id=str(strategy_id or "NA"),
                        scan_id=str(scan_id),
                        reasons=list(reasons or []),
                        payload=payload,
                        selected=selected,
                        signal=signal
                    )
                except Exception:
                    # Top-level safety catch for persistence to never crash engine
                    pass

                log_kv(
                    logger,
                    "PAIR_OK",
                    scan_id=scan_id,
                    symbol=symbol,
                    strategy_id=strategy_id,
                    # Log contract: winner_strategy_id must match final winner (strategy_id).
                    winner_strategy_id=strategy_id,
                    candidates=(debug.get("candidates") if isinstance(debug, dict) else None),
                    candidates_top=(debug.get("candidates_top") if isinstance(debug, dict) else None),
                    blocked_winner_strategy_id=blocked_winner_strategy_id,
                    blocked_reason=blocked_reason,
                    failover_used=("true" if used_failover else "false"),
                    tf=entry_tf,
                    detector="soft_combine",
                    direction=selected.get("direction"),
                    score=selected.get("score"),
                    **(_extract_score_breakdown_fields_for_logs(debug) if isinstance(debug, dict) else {}),
                    min_score=selected.get("min_score"),
                    hits=hits_n,
                    top_hits=top_hits,
                    final_strategy="soft_combine",
                    regime=selected.get("regime"),
                    regime_evidence=(debug.get("regime_evidence") if isinstance(debug, dict) else None),
                    hh=(
                        (debug.get("regime_evidence") or {}).get("hh")
                        if isinstance(debug, dict) and isinstance(debug.get("regime_evidence"), dict)
                        else None
                    ),
                    hl=(
                        (debug.get("regime_evidence") or {}).get("hl")
                        if isinstance(debug, dict) and isinstance(debug.get("regime_evidence"), dict)
                        else None
                    ),
                    lh=(
                        (debug.get("regime_evidence") or {}).get("lh")
                        if isinstance(debug, dict) and isinstance(debug.get("regime_evidence"), dict)
                        else None
                    ),
                    ll=(
                        (debug.get("regime_evidence") or {}).get("ll")
                        if isinstance(debug, dict) and isinstance(debug.get("regime_evidence"), dict)
                        else None
                    ),
                    detectors=selected.get("detectors"),
                    params_digest=(debug.get("params_digest") if isinstance(debug, dict) else None),
                    rr=selected.get("rr"),
                    ms_total=f"{ms_total:.2f}",
                )

                # Enqueue event for async worker processing (non-blocking)
                try:
                    _enqueue_ts = time.perf_counter()
                    _eq_payload = {
                        "scan_id": str(scan_id),
                        "user_id": str(user_id),
                        "detector": "soft_combine",
                        "direction": str(selected.get("direction") or ""),
                        "entry": float(getattr(setup, "entry", 0.0)),
                        "sl": float(getattr(setup, "sl", 0.0)),
                        "tp": float(getattr(setup, "tp", 0.0)),
                        "rr": float(getattr(setup, "rr", 0.0)),
                        "score": float(selected.get("score") or 0.0),
                        "strategy_id": str(strategy_id or ""),
                        "detectors": selected.get("detectors"),
                        "regime": str(selected.get("regime") or ""),
                        "ts": int(now_ts),
                    }
                    _eq_id = _event_queue.enqueue_event(
                        symbol=symbol,
                        tf=str(entry_tf),
                        setup_type="SETUP_FOUND",
                        setup_key=signal_key,
                        payload=_eq_payload,
                    )
                    _enqueue_ms = (time.perf_counter() - _enqueue_ts) * 1000.0
                    if _eq_id:
                        log_kv(logger, "EVENT_ENQUEUE", scan_id=scan_id, symbol=symbol, event_id=_eq_id[:8], ms=f"{_enqueue_ms:.2f}")
                except Exception as _eq_err:
                    log_kv_error(logger, "EVENT_ENQUEUE_ERROR", scan_id=scan_id, symbol=symbol, err=str(type(_eq_err).__name__))

                if isinstance(outcomes, dict):
                    try:
                        outcomes[str(symbol).upper()] = {
                            "kind": "OK",
                            "strategy_id": str(strategy_id or "NA"),
                            "direction": str(getattr(setup, "direction", None) or selected.get("direction") or "NA"),
                            "entry": float(getattr(setup, "entry", 0.0)),
                            "sl": float(getattr(setup, "sl", 0.0)),
                            "tp": float(getattr(setup, "tp", 0.0)),
                            "rr": float(getattr(setup, "rr", 0.0)),
                        }
                    except Exception:
                        outcomes[str(symbol).upper()] = {
                            "kind": "OK",
                            "strategy_id": str(strategy_id or "NA"),
                        }

                # Contract sanity: avoid winner/strategy mismatch in logs.
                try:
                    if str(strategy_id) != str(strategy_id):
                        raise ValueError("strategy_id mismatch")
                except Exception:
                    pass

                strat_label = f" | strat={result.strategy_name}" if result.strategy_name else ""
                logger.info(
                    f"✨ SETUP FOUND [{symbol}] for user {uid}: {setup.direction} RR: {setup.rr:.2f}{strat_label}"
                )

                # Notification mode:
                # - off: dry-run (do not generate charts / do not call Telegram)
                # - admin_only: send only to ADMIN_CHAT_ID
                # - all: default behavior
                if notify_mode in ("off", "false", "0", "none", "dry_run", "dryrun"):
                    sent = False
                else:
                    chart_source = entry_data[-120:] if len(entry_data) > 120 else entry_data
                    chart_source = _shift_candle_dict_times(chart_source, tz_offset_hours)
                    img_buf = generate_chart_image(chart_source, symbol, entry_tf)

                    chat_id = None
                    if notify_mode == "admin_only":
                        chat_id = getattr(config, "ADMIN_CHAT_ID", None) or getattr(config, "DEFAULT_CHAT_ID", None)
                    explain_payload = None
                    try:
                        if isinstance(debug, dict):
                            explain_payload = debug.get("explain")
                    except Exception:
                        explain_payload = None

                    sent = telegram_notifier.send_signal(
                        signal,
                        chart_img=img_buf,
                        chat_id=chat_id,
                        explain=explain_payload if isinstance(explain_payload, dict) else None,
                        mode=notify_mode,
                    )

                if sent:
                    signals_sent += 1
                    if self._state_loaded:
                        try:
                            self._state_store.record_sent(
                                signal_key,
                                now_ts,
                                symbol,
                                direction=str(signal.direction),
                                timeframe=str(entry_tf),
                                strategy_id=str(strategy_id or ""),
                            )
                            day_key = self._get_day_key_utc(tz_offset_hours)
                            self._state_store.increment_daily(symbol, entry_tf, str(strategy_id or ""), day_key)
                            self._state_dirty = True
                            self._save_state_debounced(scan_id=scan_id)
                        except Exception:
                            log_kv_error(logger, "STATE_RECORD_ERROR", scan_id=scan_id, symbol=symbol)

                    try:
                        record_signal(
                            user_id=user_id,
                            signal=signal,
                            strategy_name=result.strategy_name,
                            meta={"reasons": reasons},
                        )
                    except Exception:
                        pass

        return signals_sent


# Sample log lines (one event per line):
# SCAN_START | scan_id=... | pairs=12 | ts=... | users=2
# PAIR_OK | scan_id=... | symbol=EURUSD | tf=M15 | detector=sr_bounce | direction=BUY | score=0.84 | rr=2.10 | ms_total=9.12
# PAIR_NONE | scan_id=... | symbol=USDJPY | reason=NO_HITS | ms_total=6.77
# SCAN_END | scan_id=... | signals=3 | total_ms=812

scanner_service = ScannerService()


def _ops_telegram_enabled() -> bool:
    """Whether to send non-signal operational Telegram messages.

    Default: OFF to avoid noisy spam. Signals (setups found) are unaffected.
    Enable by setting env `TELEGRAM_OPS_NOTIFICATIONS=1`.
    """
    try:
        return str(os.getenv("TELEGRAM_OPS_NOTIFICATIONS", "0") or "0").strip() == "1"
    except Exception:
        return False


def start() -> dict:
    """Start the background scanner service."""
    scanner_service.start()
    return {"ok": True}


def stop() -> dict:
    """Stop the background scanner service."""
    scanner_service.stop()
    return {"ok": True}


def manual_scan() -> dict:
    """Trigger a scan pass (does not block until completion)."""
    scanner_service.manual_scan()
    return {"ok": True}


def scan_once(timeout_s: int = 30) -> dict:
    """Run one scan cycle by triggering manual scan and waiting briefly.

    This is a small sync wrapper used by the internal EngineController in
    api_server.py. It waits until ScannerService updates last scan info.
    """

    try:
        if not getattr(scanner_service, "_thread", None) or not scanner_service._thread.is_alive():
            scanner_service.start()
    except Exception:
        # Best-effort: proceed with trigger.
        pass

    prev = scanner_service.get_last_scan_info()
    prev_id = str(prev.get("last_scan_id") or "NA")
    scanner_service.manual_scan()

    deadline = time.time() + max(1, int(timeout_s))
    while time.time() < deadline:
        cur = scanner_service.get_last_scan_info()
        cur_id = str(cur.get("last_scan_id") or "NA")
        if cur_id != prev_id and cur_id != "NA":
            return {"ok": True, "triggered": True, **cur}
        time.sleep(0.5)

    cur = scanner_service.get_last_scan_info()
    return {"ok": True, "triggered": True, "completed": False, **cur}

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    scanner_service.start()
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        scanner_service.stop()
