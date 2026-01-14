from __future__ import annotations
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from datetime import datetime, timezone
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi import Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio

# Backward-compatible exports for tests/legacy callers.
try:
    from watchlist_union import get_union_watchlist  # type: ignore
except Exception:
    def get_union_watchlist(*_args: Any, **_kwargs: Any) -> list[str]:  # type: ignore
        return []

try:
    import scanner_service as ss  # type: ignore
except Exception:  # pragma: no cover
    ss = None  # type: ignore

APP_START = time.time()
app = FastAPI(title="JKM-AI-BOT API", version="0.1.0")

def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "y", "on"}


cors_allow_all = _env_bool("CORS_ALLOW_ALL", default=False)
if cors_allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"]
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://jkmcopilot.com",
            "https://www.jkmcopilot.com",
        ],
        allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"]
    )

# ---- STARTUP: launch background scanner scheduler ----
@app.on_event("startup")
def _startup_scanner():
    """Launch the APScheduler-based 5-minute scan cycle on server start."""
    import logging
    _log = logging.getLogger("api_server.startup")

    # Enforce privacy mode - purge local user artifacts on startup
    try:
        from core.privacy import enforce_privacy_on_startup
        enforce_privacy_on_startup(verbose=True)
    except Exception as e:
        _log.warning(f"Privacy enforcement failed: {e}")

    def _seed_owner_admin_strategy() -> None:
        """Seed a default strategy for the owner admin only.

        This keeps the product rule: normal users must explicitly choose strategies,
        while allowing the owner/admin account to have a known working default.
        """

        owner_user_id = (os.getenv("OWNER_ADMIN_USER_ID") or os.getenv("OWNER_USER_ID") or "").strip()
        if not owner_user_id:
            return

        # In privacy mode, we avoid any sqlite-based lookup/seeding on the backend.
        try:
            from core.privacy import privacy_mode_enabled

            if privacy_mode_enabled():
                return
        except Exception:
            pass

        # Convenience: allow passing an email instead of a raw user_id.
        # This resolves to the backend's user_id stored in sqlite.
        if "@" in owner_user_id:
            try:
                from user_db import init_db, get_account_by_email

                init_db()
                acc = get_account_by_email(owner_user_id)
                resolved = str((acc or {}).get("user_id") or "").strip()
                if resolved:
                    owner_user_id = resolved
                else:
                    _log.warning(
                        "OWNER_ADMIN_USER_ID looks like email but was not found in backend user_db: %s",
                        owner_user_id,
                    )
                    return
            except Exception:
                return

        try:
            from core.user_strategies_store import load_user_strategies, save_user_strategies

            existing = load_user_strategies(owner_user_id)
            if existing:
                return

            # Previously-default strategy (range_reversal_v1), saved under a friendly name.
            default_owner_strategy = {
                "strategy_id": "jkm_strategy",
                "name": "JKM strategy",
                "enabled": True,
                "priority": 50,
                "engine_version": "indicator_free_v1",
                "min_score": 1.0,
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": ["range_box_edge", "sr_bounce", "fakeout_trap"],
                "detector_weights": {"range_box_edge": 1.2},
                "family_weights": {"sr": 1.1, "range": 1.0},
                "conflict_epsilon": 0.05,
                "confluence_bonus_per_family": 0.25,
            }

            res = save_user_strategies(owner_user_id, [default_owner_strategy])
            try:
                _log.info(
                    "Seeded owner admin strategy user_id=%s count=%s warnings=%s",
                    owner_user_id,
                    int(len(res.get("strategies") or [])),
                    list(res.get("warnings") or []),
                )
            except Exception:
                pass
        except Exception as e:
            _log.error("Failed seeding owner admin strategy: %s", e, exc_info=True)

    try:
        import scanner_service
        _seed_owner_admin_strategy()
        result = scanner_service.start()
        _log.info("Scanner scheduler started: %s", result)
    except Exception as e:
        _log.error("Failed to start scanner scheduler: %s", e, exc_info=True)

def _ensure_writable_dir(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        t = p / ".write_test"
        t.write_text("ok", encoding="utf-8")
        t.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _signals_path() -> Path:
    state_dir = Path(os.getenv("STATE_DIR") or "/app/state")
    return state_dir / "signals.jsonl"


def _estimate_lines_fast(file_path: Path) -> int:
    try:
        st = file_path.stat()
    except Exception:
        return 0

    size = int(getattr(st, "st_size", 0) or 0)
    if size <= 0:
        return 0

    sample_size = min(64 * 1024, size)
    try:
        with file_path.open("rb") as f:
            f.seek(-sample_size, os.SEEK_END)
            tail = f.read(sample_size)
    except Exception:
        return 0

    newlines = tail.count(b"\n")
    if newlines <= 0:
        return 1

    avg_bytes_per_line = max(1, sample_size // newlines)
    return max(1, size // avg_bytes_per_line)


def _read_last_json_objects(file_path: Path, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    if not file_path.exists():
        return []

    # Read from the end in chunks until we have enough lines.
    # We parse from the end so we can return the last N valid JSON objects.
    chunk_size = 8192
    max_bytes = 4 * 1024 * 1024  # safety cap
    data = b""
    read_total = 0

    try:
        with file_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            while pos > 0 and read_total < max_bytes and data.count(b"\n") < (limit * 3 + 10):
                step = min(chunk_size, pos)
                pos -= step
                f.seek(pos)
                block = f.read(step)
                read_total += len(block)
                data = block + data
    except Exception:
        return []

    text = data.decode("utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    out: list[dict[str, Any]] = []
    for ln in reversed(lines):
        if len(out) >= limit:
            break
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)

    out.reverse()
    return out

@app.get("/health")
def health():
    massive_key = (os.getenv("MASSIVE_API_KEY") or "").strip()
    # MASSIVE_BASE_URL is optional; provider defaults to https://api.massive.com.
    massive_base_url = (os.getenv("MASSIVE_BASE_URL") or "").strip() or "https://api.massive.com"
    data_provider = (os.getenv("DATA_PROVIDER") or os.getenv("MARKET_DATA_PROVIDER") or "").strip().lower()
    state_dir = Path(os.getenv("STATE_DIR") or "/app/state")
    writable = _ensure_writable_dir(state_dir)

    signals_file = state_dir / "signals.jsonl"
    signals_exists = signals_file.exists()
    signals_lines_estimate = _estimate_lines_fast(signals_file) if signals_exists else 0

    # Cache readiness: best-effort snapshot of in-memory market cache.
    cache_ready = False
    cache_note = "not_loaded"
    cache_symbols = 0
    try:
        from market_data_cache import market_cache  # local module, no external deps

        syms = market_cache.get_all_symbols()
        cache_symbols = int(len(syms))
        cache_ready = cache_symbols > 0
        cache_note = "ok" if cache_ready else "empty"
    except Exception:
        cache_ready = False
        cache_note = "unavailable"
        cache_symbols = 0

    # DB readiness: v0.1 backend does not require a DB.
    db_ready = True
    db_note = "not_configured"
    return {
        "ok": True,
        "ts": int(time.time()),
        "uptime_s": int(time.time() - APP_START),
        "hostname": socket.gethostname(),
        "provider_configured": bool(massive_key and massive_base_url),
        "provider_env": data_provider or None,
        "massive_api_key_present": bool(massive_key),
        "massive_base_url_present": bool(massive_base_url),
        "state_dir": str(state_dir),
        "state_writable": writable,
        "signals_file_exists": bool(signals_exists),
        "signals_lines_estimate": int(signals_lines_estimate),
        "cache": {"ready": bool(cache_ready), "note": str(cache_note), "symbols": int(cache_symbols)},
        "db": {"ready": bool(db_ready), "note": str(db_note)},
    }

@app.get("/api/signals")
def list_signals(
    limit: int = Query(50, ge=1, le=500),
    symbol: str | None = Query(None, description="Filter by symbol (case-insensitive)"),
    include_outcomes: bool = Query(True, description="Include SL/TP hit outcomes"),
):
    """List signals with optional symbol filter. Newest first."""
    path = _signals_path()
    all_signals = _read_last_json_objects(path, limit * 3 if symbol else limit)  # over-fetch if filtering
    
    if symbol:
        sym_upper = symbol.strip().upper()
        filtered = [s for s in all_signals if str(s.get("symbol") or "").upper() == sym_upper]
        signals_list = filtered[:limit]
    else:
        signals_list = all_signals[:limit]
    
    # Attach outcomes if requested
    if include_outcomes:
        try:
            from core.outcome_tracker import load_outcomes
            outcomes = load_outcomes()
            for sig in signals_list:
                sig_id = sig.get("signal_id")
                if sig_id and sig_id in outcomes:
                    sig["outcome"] = outcomes[sig_id].get("outcome", "PENDING")
                    sig["outcome_data"] = outcomes[sig_id]
                else:
                    sig["outcome"] = "PENDING"
        except Exception:
            pass
    
    return signals_list


@app.post("/api/signals")
def append_signal(payload: dict[str, Any] = Body(...)):
    state_dir = Path(os.getenv("STATE_DIR") or "/app/state")
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # If we cannot create state dir, fail gracefully (no crash).
        return {"ok": False, "error": "state_dir_not_writable"}

    if "ts" not in payload:
        payload["ts"] = int(time.time())

    file_path = state_dir / "signals.jsonl"
    try:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with file_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        return {"ok": False, "error": "write_failed"}

    return {"ok": True}
# =========================
# Engine control v0.1 (internal-key protected)
# =========================
import os
import time
import threading
from typing import Any, Callable, Optional

from fastapi import Header, HTTPException, Depends

def require_internal_key(
    x_internal_api_key: Optional[str] = Header(default=None, alias="x-internal-api-key")
) -> bool:
    expected = os.getenv("INTERNAL_API_KEY")
    if not expected:
        # safer: misconfigured server
        raise HTTPException(status_code=500, detail="INTERNAL_API_KEY not configured")
    if not x_internal_api_key or x_internal_api_key != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
    return True


@app.get("/api/admin/resolve-user", dependencies=[Depends(require_internal_key)])
def admin_resolve_user(email: str = Query(..., description="User email to resolve to backend user_id")):
    """Resolve backend user_id by email.

    This is useful for ops (e.g., setting OWNER_ADMIN_USER_ID).
    Never crashes if DB is missing; returns ok:true with found=false.
    """

    em = str(email or "").strip()
    if not em:
        raise HTTPException(status_code=400, detail="email required")

    try:
        from user_db import init_db, get_account_by_email

        init_db()
        acc = get_account_by_email(em)
        if not acc:
            return {"ok": True, "found": False, "email": em, "user_id": None}
        return {"ok": True, "found": True, "email": em, "user_id": acc.get("user_id")}
    except Exception:
        return {"ok": True, "found": False, "email": em, "user_id": None}

class EngineController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_at = time.time()
        self.running: bool = False
        self.last_scan_ts: Optional[int] = None
        self.last_error: Optional[str] = None

    def _resolve_scan_once(self) -> Callable[[], Any]:
        """
        Tries to find a 'scan once' function from scanner_service.py without hard-coding.
        You can later replace this with the exact function call.
        """
        import scanner_service as ss  # local import to avoid import-time crashes
        for name in ("scan_once", "run_once", "manual_scan", "do_scan_once", "scan_cycle"):
            fn = getattr(ss, name, None)
            if callable(fn):
                return fn
        raise RuntimeError("No scan-once function found in scanner_service.py")

    def _loop(self, cadence_s: int = 300) -> None:
        while not self._stop_event.is_set():
            try:
                self.manual_scan()
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            # sleep in small chunks so stop feels responsive
            for _ in range(max(1, cadence_s)):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def start(self) -> dict:
        with self._lock:
            if self.running and self._thread and self._thread.is_alive():
                return self.status()

            self._stop_event.clear()
            self.last_error = None

            self._thread = threading.Thread(target=self._loop, name="engine-loop", daemon=True)
            self._thread.start()
            self.running = True
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
            self.running = False
            return self.status()

    def manual_scan(self) -> dict:
        try:
            scan_once = self._resolve_scan_once()
            result = scan_once()
            self.last_scan_ts = int(time.time())
            self.last_error = None
            return {"ok": True, "result": result, "ts": self.last_scan_ts}
        except Exception as e:
            self.last_scan_ts = int(time.time())
            self.last_error = f"{type(e).__name__}: {e}"
            return {"ok": False, "error": self.last_error, "ts": self.last_scan_ts}

    def status(self) -> dict:
        uptime_s = int(time.time() - self._started_at)
        alive = bool(self._thread and self._thread.is_alive())
        return {
            "ok": True,
            "running": bool(self.running and alive),
            "uptime_s": uptime_s,
            "last_scan_ts": self.last_scan_ts,
            "last_error": self.last_error,
        }

_engine = EngineController()

@app.get("/api/engine/status", dependencies=[Depends(require_internal_key)])
def engine_status():
    """Return real scanner status (not EngineController's misleading state)."""
    import scanner_service as ss
    import config as cfg

    # Truth source: real scanner thread state
    thread = getattr(ss.scanner_service, "_thread", None)
    stop_event = getattr(ss.scanner_service, "_stop_event", None)
    running = bool(thread and thread.is_alive() and (stop_event is None or not stop_event.is_set()))

    # Last scan info from scanner
    last_info = ss.scanner_service.get_last_scan_info()
    last_scan_id = last_info.get("last_scan_id")
    last_scan_ts_raw = last_info.get("last_scan_ts")

    # Convert to epoch int
    last_scan_ts: int = 0
    if last_scan_ts_raw and last_scan_ts_raw != "NA":
        try:
            if isinstance(last_scan_ts_raw, (int, float)):
                last_scan_ts = int(last_scan_ts_raw)
            elif isinstance(last_scan_ts_raw, str):
                # Try ISO parse
                dt = datetime.fromisoformat(last_scan_ts_raw.replace("Z", "+00:00"))
                last_scan_ts = int(dt.timestamp())
        except Exception:
            last_scan_ts = 0

    if last_scan_id == "NA":
        last_scan_id = None

    # Cadence from config (best-effort)
    cadence_sec: int | None = None
    try:
        cadence_sec = int(getattr(cfg, "SCAN_INTERVAL_SECONDS", 300) or 300)
    except Exception:
        cadence_sec = 300

    # Last error (best-effort from EngineController fallback)
    last_error = _engine.last_error

    return {
        "ok": True,
        "running": running,
        "last_scan_ts": last_scan_ts,
        "last_scan_id": last_scan_id,
        "cadence_sec": cadence_sec,
        "last_error": last_error,
    }

@app.post("/api/engine/start", dependencies=[Depends(require_internal_key)])
def engine_start():
    return _engine.start()

@app.post("/api/engine/stop", dependencies=[Depends(require_internal_key)])
def engine_stop():
    return _engine.stop()

@app.post("/api/engine/manual-scan", dependencies=[Depends(require_internal_key)])
def engine_manual_scan():
    """Trigger a real scan cycle via scanner_service.scan_once()."""
    import scanner_service as ss
    try:
        result = ss.scan_once(timeout_s=30)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/api/scan/manual-explain", dependencies=[Depends(require_internal_key)])
def scan_manual_explain(payload: dict):
    """Run a one-off manual scan for a specific user and return a Telegram-ready explanation.

    Payload:
      - user_id: str (required)
      - symbols: list[str] (optional)
    """

    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    symbols = payload.get("symbols")
    if symbols is not None and not isinstance(symbols, list):
        raise HTTPException(status_code=400, detail="symbols must be a list")

    import scanner_service as ss

    return ss.scanner_service.manual_scan_explain(user_id=user_id, symbols=symbols)

# Dashboard login flow sometimes calls this; stop returning 404.
# Keep it internal-key protected (recommended).
@app.post("/api/auth/register", dependencies=[Depends(require_internal_key)])
def auth_register(payload: dict):
    # v0.1 minimal: just acknowledge; later you can store into sqlite user_db.py
    return {"ok": True, "registered": True, "payload_keys": list(payload.keys())}


# =========================
# Admin backfill (internal-key protected)
# =========================


@app.post("/api/admin/backfill", dependencies=[Depends(require_internal_key)])
def admin_backfill(payload: dict):
    """Run a short backfill job into /app/state/marketdata.

    Intended for ops validation (small ranges). Heavy multi-year backfills should
    use scripts/backfill_massive.py.

    Payload:
      - symbol: str (required)
      - timeframe: str (default: m5)
      - days: int (default: 7)
      - chunk_days: int (default: 1)
    """

    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")

    timeframe = str(payload.get("timeframe") or "m5").strip().lower() or "m5"
    days = int(payload.get("days") or 7)
    chunk_days = int(payload.get("chunk_days") or 1)
    days = max(1, min(days, 30))
    chunk_days = max(1, min(chunk_days, 14))

    # Run in background so API stays responsive.
    def _job() -> None:
        import time
        import logging
        from datetime import datetime, timedelta, timezone

        from core.ingest_debug import log_ingest_event
        from core.marketdata_store import append as store_append
        from data_providers.factory import create_provider
        from data_providers.models import Candle, candles_to_cache_dicts
        from data_providers.massive_provider import to_massive_ticker

        provider = create_provider(name="massive")

        job_logger = logging.getLogger("uvicorn.error")

        job_logger.info(
            "ADMIN_BACKFILL_START symbol=%s tf=%s days=%s chunk_days=%s",
            symbol,
            timeframe,
            days,
            chunk_days,
        )

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        cur = start
        step = timedelta(days=chunk_days)
        while cur < end:
            nxt = min(end, cur + step)
            est = int((nxt - cur).total_seconds() / 300) + 20
            t0 = time.perf_counter()
            candles = provider.fetch_candles(
                symbol,
                timeframe=timeframe,
                max_count=est,
                limit=est,
                since_ts=cur,
                until_ts=nxt,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0
            cache_dicts = candles_to_cache_dicts(candles) if candles else []
            _, persisted_path = store_append(symbol, timeframe, cache_dicts)

            job_logger.info(
                "ADMIN_BACKFILL_CHUNK symbol=%s tf=%s start=%s end=%s fetched=%d wrote=%d ms=%.2f",
                symbol,
                timeframe,
                cur.isoformat(),
                nxt.isoformat(),
                int(len(candles or [])),
                int(len(cache_dicts)),
                float(dt_ms),
            )

            massive_ticker = None
            try:
                massive_ticker = to_massive_ticker(symbol)
            except Exception:
                massive_ticker = None

            log_ingest_event(
                job_logger,
                "admin_backfill_chunk",
                provider=getattr(provider, "name", "unknown"),
                symbol=symbol,
                timeframe=timeframe,
                candles_count=int(len(cache_dicts)),
                requested_start=cur.isoformat(),
                requested_end=nxt.isoformat(),
                persist_path=str(persisted_path),
                duration_ms=dt_ms,
                extra={
                    "internalSymbol": symbol,
                    "massiveTicker": massive_ticker,
                    "fetchedCandles": int(len(candles or [])),
                },
            )
            # small pacing to be gentle
            time.sleep(0.1)
            cur = nxt

    t = threading.Thread(target=_job, name=f"admin-backfill-{symbol}", daemon=True)
    t.start()
    return {"ok": True, "started": True, "symbol": symbol, "timeframe": timeframe, "days": days, "chunk_days": chunk_days}


# ============================================================================
# BACKTEST API
# ============================================================================

@app.post("/api/backtest", dependencies=[Depends(require_internal_key)])
def run_backtest(payload: dict = Body(...)):
    """Run a simple backtest against historical signals.
    
    Body: {
        "strategy_id": "my_strategy",  # optional: filter by strategy
        "detectors": ["range_box_edge", "sr_bounce"],  # optional: filter signals that used these detectors
        "symbol": "XAUUSD",  # optional: filter by symbol
        "days": 30,  # optional: how many days back (default 30)
    }
    
    Returns statistics about matched signals.
    """
    strategy_id = (payload.get("strategy_id") or "").strip() or None
    detectors = payload.get("detectors") or []
    symbol_filter = (payload.get("symbol") or "").strip().upper() or None
    days = int(payload.get("days") or 30)
    
    path = _signals_path()
    if not path.exists():
        return {
            "ok": True,
            "total_matched": 0,
            "ok_count": 0,
            "none_count": 0,
            "hit_rate": None,
            "by_symbol": {},
            "signals_sample": [],
        }
    
    from collections import defaultdict
    
    now_ts = int(time.time())
    cutoff_ts = now_ts - (days * 86400)
    
    matched_signals = []
    by_symbol: dict = defaultdict(lambda: {"ok": 0, "none": 0, "total": 0})
    
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                
                # Parse timestamp
                ts = obj.get("ts") or obj.get("created_at")
                sig_ts = 0
                if isinstance(ts, (int, float)):
                    sig_ts = int(ts)
                elif isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        sig_ts = int(dt.timestamp())
                    except Exception:
                        pass
                
                if sig_ts < cutoff_ts:
                    continue
                
                # Symbol filter
                sig_symbol = str(obj.get("symbol") or "").upper()
                if symbol_filter and sig_symbol != symbol_filter:
                    continue
                
                # Detector filter (check if signal used any of the specified detectors)
                if detectors:
                    sig_evidence = obj.get("evidence") or {}
                    sig_detectors = sig_evidence.get("detectors_triggered") or []
                    if isinstance(sig_detectors, dict):
                        sig_detectors = list(sig_detectors.keys())
                    if not any(d in sig_detectors for d in detectors):
                        continue
                
                # Strategy filter (check explain or evidence for strategy_id)
                if strategy_id:
                    sig_strategy = obj.get("explain", {}).get("strategy_id") or obj.get("evidence", {}).get("strategy_id")
                    if sig_strategy != strategy_id:
                        continue
                
                status = str(obj.get("status") or "").upper()
                
                # Get SL/TP hit outcome from outcome tracker
                entry = obj.get("entry")
                sl = obj.get("sl")
                tp = obj.get("tp")
                direction = obj.get("direction")
                
                outcome = "PENDING"
                outcome_data = None
                
                # Check if we have outcome stored
                try:
                    from core.outcome_tracker import get_signal_outcome
                    stored_outcome = get_signal_outcome(obj.get("signal_id"))
                    if stored_outcome:
                        outcome = stored_outcome.get("outcome", "PENDING")
                        outcome_data = stored_outcome
                except Exception:
                    pass
                
                matched_signals.append({
                    "signal_id": obj.get("signal_id"),
                    "symbol": sig_symbol,
                    "tf": obj.get("tf") or obj.get("timeframe"),
                    "direction": direction,
                    "status": status,
                    "rr": obj.get("rr"),
                    "created_at": sig_ts,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "outcome": outcome,
                })
                
                by_symbol[sig_symbol]["total"] += 1
                if outcome == "WIN":
                    by_symbol[sig_symbol]["wins"] = by_symbol[sig_symbol].get("wins", 0) + 1
                elif outcome == "LOSS":
                    by_symbol[sig_symbol]["losses"] = by_symbol[sig_symbol].get("losses", 0) + 1
                else:
                    by_symbol[sig_symbol]["pending"] = by_symbol[sig_symbol].get("pending", 0) + 1
                    
                if status == "OK":
                    by_symbol[sig_symbol]["ok"] += 1
                elif status == "NONE":
                    by_symbol[sig_symbol]["none"] += 1
    except Exception:
        pass
    
    total_matched = len(matched_signals)
    ok_count = sum(1 for s in matched_signals if s.get("status") == "OK")
    none_count = sum(1 for s in matched_signals if s.get("status") == "NONE")
    
    # Outcome-based stats (real win/loss from SL/TP hits)
    wins = sum(1 for s in matched_signals if s.get("outcome") == "WIN")
    losses = sum(1 for s in matched_signals if s.get("outcome") == "LOSS")
    pending = sum(1 for s in matched_signals if s.get("outcome") == "PENDING")
    
    # Real win rate based on SL/TP hits
    real_win_rate = None
    decided = wins + losses
    if decided > 0:
        real_win_rate = round(wins / decided, 4)
    
    hit_rate = None
    denom = ok_count + none_count
    if denom > 0:
        hit_rate = round(ok_count / denom, 4)
    
    # Add hit_rate to by_symbol
    symbol_stats = {}
    for sym, stats in by_symbol.items():
        d = stats["ok"] + stats["none"]
        hr = round(stats["ok"] / d, 4) if d > 0 else None
        sym_wins = stats.get("wins", 0)
        sym_losses = stats.get("losses", 0)
        sym_decided = sym_wins + sym_losses
        sym_wr = round(sym_wins / sym_decided, 4) if sym_decided > 0 else None
        symbol_stats[sym] = {
            **stats, 
            "hit_rate": hr,
            "real_win_rate": sym_wr,
        }
    
    return {
        "ok": True,
        "total_matched": total_matched,
        "ok_count": ok_count,
        "none_count": none_count,
        "hit_rate": hit_rate,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "real_win_rate": real_win_rate,
        "by_symbol": symbol_stats,
        "signals_sample": matched_signals[:20],  # Return first 20 as sample
        "filters": {
            "strategy_id": strategy_id,
            "detectors": detectors,
            "symbol": symbol_filter,
            "days": days,
        },
    }


# ============================================================================
# SIMULATION BACKTEST API - Run detectors on historical candle data
# ============================================================================

@app.post("/api/backtest/simulate", dependencies=[Depends(require_internal_key)])
def run_simulation_backtest(payload: dict = Body(...)):
    """Run a simulation backtest - run detectors on historical candle data.
    
    Body: {
        "strategy_id": "my_strategy",  # optional: use strategy's detectors
        "detectors": ["range_box_edge", "sr_bounce"],  # optional: specific detectors
        "symbol": "XAUUSD",  # optional: specific symbol (default: all)
        "days": 90,  # how many days back (default 90)
        "min_rr": 2.0,  # minimum R:R filter (default 2.0)
    }
    
    Process:
    1. Load historical candle data for the specified period
    2. Run selected detectors on each candle bar
    3. When detector fires, record entry/sl/tp
    4. Check if SL or TP was hit in subsequent candles
    5. Return win/loss statistics
    """
    import logging
    import traceback
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict
    
    _log = logging.getLogger("backtest.simulate")
    
    # Wrap entire function in try/except for 500 error prevention
    try:
        return _run_simulation_backtest_impl(payload, _log)
    except Exception as e:
        _log.error("Simulation backtest failed: %s\n%s", e, traceback.format_exc())
        return {
            "ok": False,
            "error": f"Simulation failed: {str(e)[:200]}",
            "error_type": type(e).__name__,
            "total_entries": 0,
            "wins": 0,
            "losses": 0,
            "pending": 0,
            "win_rate": None,
        }


def _run_simulation_backtest_impl(payload: dict, _log):
    """Internal implementation of simulation backtest."""
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict
    
    strategy_id = (payload.get("strategy_id") or "").strip() or None
    detector_names = payload.get("detectors") or []
    symbol_filter = (payload.get("symbol") or "").strip().upper() or None
    days = int(payload.get("days") or 90)
    min_rr = float(payload.get("min_rr") or 2.0)
    
    # Get detectors from strategy if specified
    if strategy_id and not detector_names:
        try:
            from core.user_strategies_store import load_all_strategies
            all_strats = load_all_strategies()
            for strat in all_strats:
                if strat.get("strategy_id") == strategy_id:
                    detector_names = strat.get("detectors", [])
                    min_rr = strat.get("min_rr", min_rr)
                    break
        except Exception as e:
            _log.warning("Could not load strategy %s: %s", strategy_id, e)
    
    if not detector_names:
        return {
            "ok": False,
            "error": "No detectors specified. Select a strategy or provide detector list.",
            "total_entries": 0,
            "wins": 0,
            "losses": 0,
            "pending": 0,
            "win_rate": None,
        }
    
    # Get symbols to backtest
    symbols_to_test = []
    if symbol_filter:
        symbols_to_test = [symbol_filter]
    else:
        # Use canonical symbols
        symbols_to_test = [
            "EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD",
            "NZDUSD", "EURJPY", "GBPJPY", "XAUUSD", "BTCUSD",
        ]
    
    # Load detector registry
    try:
        from detectors.registry import DETECTOR_REGISTRY
    except ImportError:
        return {"ok": False, "error": "Detector registry not available"}
    
    # Validate detectors exist
    valid_detectors = []
    for d_name in detector_names:
        if d_name in DETECTOR_REGISTRY:
            valid_detectors.append(d_name)
        else:
            _log.warning("Detector %s not found in registry", d_name)
    
    if not valid_detectors:
        return {"ok": False, "error": f"No valid detectors found. Available: {list(DETECTOR_REGISTRY.keys())[:10]}..."}
    
    # Results tracking
    all_entries = []
    wins = 0
    losses = 0
    pending = 0
    by_symbol = defaultdict(lambda: {"entries": 0, "wins": 0, "losses": 0, "pending": 0})
    by_detector = defaultdict(lambda: {"entries": 0, "wins": 0, "losses": 0})
    
    # Time range
    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(days=days)
    
    # Load candle data from market_cache.json (not in-memory cache singleton)
    from pathlib import Path
    from market_data_cache import MarketDataCache
    
    cache_path = Path("state/market_cache.json")
    temp_cache = MarketDataCache(max_len=20000)
    loaded_symbols = 0
    if cache_path.exists():
        try:
            loaded_symbols = temp_cache.load_json(str(cache_path))
            _log.info("Loaded %d symbols from market_cache.json", loaded_symbols)
        except Exception as e:
            _log.error("Failed to load market_cache.json: %s", e)
            return {
                "ok": False,
                "error": f"Market data file corrupted or unreadable: {e}",
                "total_entries": 0,
                "wins": 0,
                "losses": 0,
                "pending": 0,
                "win_rate": None,
            }
    else:
        _log.warning("market_cache.json not found at %s", cache_path)
        return {
            "ok": False,
            "error": f"No market data found. Cache file missing: {cache_path}",
            "total_entries": 0,
            "wins": 0,
            "losses": 0,
            "pending": 0,
            "win_rate": None,
        }
    
    if loaded_symbols == 0:
        return {
            "ok": False,
            "error": "Market data file exists but contains no valid symbols",
            "total_entries": 0,
            "wins": 0,
            "losses": 0,
            "pending": 0,
            "win_rate": None,
        }
    
    # Process each symbol
    for symbol in symbols_to_test:
        try:
            # Get M5 candles from loaded cache
            m5_candles = temp_cache.get_candles(symbol)
            if not m5_candles or len(m5_candles) < 200:
                _log.debug("Not enough M5 candles for %s: %d", symbol, len(m5_candles) if m5_candles else 0)
                continue
            
            # Resample M5 to M15
            m15_candles = _resample_candles(m5_candles, 3)  # 3 x 5min = 15min
            
            if len(m15_candles) < 50:
                _log.debug("Not enough M15 candles after resample for %s: %d", symbol, len(m15_candles))
                continue
            
            # Filter to time range
            filtered_candles = []
            for c in m15_candles:
                c_time = c.get("time")
                if isinstance(c_time, datetime):
                    c_dt = c_time if c_time.tzinfo else c_time.replace(tzinfo=timezone.utc)
                elif isinstance(c_time, (int, float)):
                    c_dt = datetime.fromtimestamp(c_time, tz=timezone.utc)
                else:
                    continue
                if c_dt >= start_dt:
                    filtered_candles.append(c)
            
            if len(filtered_candles) < 20:
                continue
            
            _log.info("Backtesting %s with %d candles", symbol, len(filtered_candles))
            
            # Build H4 candles for trend detection (resample M15 to H4 = 16 bars)
            h4_candles = _resample_candles(filtered_candles, 16)  # 16 x 15min = 4 hours
            
            # Import primitives types
            from core.primitives import (
                PrimitiveResults, SwingResult, SRZoneResult, 
                TrendStructureResult, FibLevelResult
            )
            from engine_blocks import Swing, Candle
            
            # Convert dict candles to Candle dataclass objects
            def dict_to_candle(d):
                return Candle(
                    time=d.get("time"),
                    open=float(d.get("open", 0)),
                    high=float(d.get("high", 0)),
                    low=float(d.get("low", 0)),
                    close=float(d.get("close", 0)),
                )
            
            filtered_candles_obj = [dict_to_candle(c) for c in filtered_candles]
            h4_candles_obj = [dict_to_candle(c) for c in h4_candles]
            
            # Run through candles simulating real-time
            for i in range(50, len(filtered_candles_obj) - 20):  # Leave room for outcome check
                current_candles = filtered_candles_obj[:i+1]
                current_candle = current_candles[-1]
                
                # For H4 trend candles, approximate using ratio
                h4_index = min(i // 16, len(h4_candles_obj) - 1)
                current_h4_candles = h4_candles_obj[:h4_index+1] if h4_index > 0 else h4_candles_obj[:1]
                
                # Build proper PrimitiveResults from candles
                if len(current_candles) > 30:
                    recent = current_candles[-30:]
                    highs = [c.high for c in recent]
                    lows = [c.low for c in recent]
                    closes = [c.close for c in recent]
                    
                    swing_high = max(highs)
                    swing_low = min(lows)
                    last_close = closes[-1]
                    
                    # Create swing
                    swing = Swing(
                        low=swing_low,
                        high=swing_high,
                    )
                    
                    # Determine trend direction (string literal)
                    if closes[-1] > closes[0]:
                        trend_dir = "up"
                    elif closes[-1] < closes[0]:
                        trend_dir = "down"
                    else:
                        trend_dir = "flat"
                    
                    primitives = PrimitiveResults(
                        swing=SwingResult(swing=swing, direction=trend_dir, found=True),
                        sr_zones=SRZoneResult(
                            support=swing_low,
                            resistance=swing_high,
                            last_close=last_close,
                            zones=[(swing_low, swing_high)],
                        ),
                        trend_structure=TrendStructureResult(
                            direction=trend_dir,
                            structure_valid=True,
                        ),
                        fib_levels=FibLevelResult(
                            retrace={0.382: swing_low + (swing_high - swing_low) * 0.382,
                                    0.5: swing_low + (swing_high - swing_low) * 0.5,
                                    0.618: swing_low + (swing_high - swing_low) * 0.618},
                            extensions={1.618: swing_high + (swing_high - swing_low) * 0.618},
                            swing=swing,
                        ),
                    )
                else:
                    continue  # Skip if not enough data
                
                # Run each detector
                for d_name in valid_detectors:
                    try:
                        detector_class = DETECTOR_REGISTRY.get(d_name)
                        if detector_class is None:
                            continue
                        detector_instance = detector_class()
                        
                        # Default user config
                        user_config = {
                            "min_rr": min_rr,
                            "trend_tf": "H4",
                            "entry_tf": "M15",
                        }
                        
                        # Run detector with proper parameters
                        try:
                            result = detector_instance.detect(
                                pair=symbol,
                                entry_candles=current_candles,
                                trend_candles=current_h4_candles,
                                primitives=primitives,
                                user_config=user_config,
                            )
                        except Exception as det_err:
                            _log.debug("Detector %s detection error on %s: %s", d_name, symbol, det_err)
                            continue
                        
                        if result and hasattr(result, "direction"):
                            direction = result.direction
                            entry_price = result.entry if hasattr(result, "entry") else current_candle.close
                            sl = result.sl if hasattr(result, "sl") else None
                            tp = result.tp if hasattr(result, "tp") else None
                            rr = result.rr if hasattr(result, "rr") else None
                            
                            # Skip if no SL/TP or RR too low
                            if not sl or not tp:
                                continue
                            if rr and rr < min_rr:
                                continue
                            
                            # Check outcome using future candles (dict format for _check_sl_tp_hit)
                            future_candles = filtered_candles[i+1:i+100]  # Check next 100 candles (~25 hours)
                            outcome = _check_sl_tp_hit(direction, entry_price, sl, tp, future_candles)
                            
                            entry_record = {
                                "symbol": symbol,
                                "detector": d_name,
                                "direction": direction,
                                "entry": entry_price,
                                "sl": sl,
                                "tp": tp,
                                "rr": rr,
                                "outcome": outcome,
                                "time": str(current_candle.time),
                            }
                            all_entries.append(entry_record)
                            
                            by_symbol[symbol]["entries"] += 1
                            by_detector[d_name]["entries"] += 1
                            
                            if outcome == "WIN":
                                wins += 1
                                by_symbol[symbol]["wins"] += 1
                                by_detector[d_name]["wins"] += 1
                            elif outcome == "LOSS":
                                losses += 1
                                by_symbol[symbol]["losses"] += 1
                                by_detector[d_name]["losses"] += 1
                            else:
                                pending += 1
                                by_symbol[symbol]["pending"] += 1
                    
                    except Exception as e:
                        _log.debug("Detector %s error: %s", d_name, e)
                        continue
        
        except Exception as e:
            _log.warning("Error processing symbol %s: %s", symbol, e)
            continue
    
    # Calculate win rates
    total_entries = len(all_entries)
    decided = wins + losses
    win_rate = round(wins / decided, 4) if decided > 0 else None
    
    # Symbol stats with win rates
    symbol_stats = {}
    for sym, stats in by_symbol.items():
        sym_decided = stats["wins"] + stats["losses"]
        stats["win_rate"] = round(stats["wins"] / sym_decided, 4) if sym_decided > 0 else None
        symbol_stats[sym] = stats
    
    # Detector stats with win rates
    detector_stats = {}
    for det, stats in by_detector.items():
        det_decided = stats["wins"] + stats["losses"]
        stats["win_rate"] = round(stats["wins"] / det_decided, 4) if det_decided > 0 else None
        detector_stats[det] = stats
    
    return {
        "ok": True,
        "mode": "simulation",
        "total_entries": total_entries,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "win_rate": win_rate,
        "by_symbol": symbol_stats,
        "by_detector": detector_stats,
        "sample_entries": all_entries[:20],
        "filters": {
            "strategy_id": strategy_id,
            "detectors": valid_detectors,
            "symbol": symbol_filter,
            "days": days,
            "min_rr": min_rr,
        },
    }


def _resample_candles(candles: list, factor: int) -> list:
    """Resample candles by a factor (e.g., factor=3 means 3 x M5 = M15).
    
    Args:
        candles: List of candle dicts with time, open, high, low, close, volume
        factor: Number of source candles per target candle
        
    Returns:
        Resampled candle list
    """
    if not candles or factor < 1:
        return []
    
    result = []
    for i in range(0, len(candles) - factor + 1, factor):
        group = candles[i:i + factor]
        if len(group) < factor:
            break
        
        resampled = {
            "time": group[0].get("time"),
            "open": group[0].get("open"),
            "high": max(c.get("high", 0) for c in group),
            "low": min(c.get("low", float("inf")) for c in group),
            "close": group[-1].get("close"),
            "volume": sum(c.get("volume", 0) for c in group),
        }
        result.append(resampled)
    
    return result


def _check_sl_tp_hit(direction: str, entry: float, sl: float, tp: float, future_candles: list) -> str:
    """Check if SL or TP was hit in future candles.
    
    Returns: "WIN" if TP hit first, "LOSS" if SL hit first, "PENDING" if neither
    """
    if not future_candles:
        return "PENDING"
    
    for candle in future_candles:
        high = candle.get("high", 0)
        low = candle.get("low", 0)
        
        if direction == "BUY":
            # For BUY: SL is below entry, TP is above entry
            if low <= sl:
                return "LOSS"
            if high >= tp:
                return "WIN"
        else:  # SELL
            # For SELL: SL is above entry, TP is below entry
            if high >= sl:
                return "LOSS"
            if low <= tp:
                return "WIN"
    
    return "PENDING"


# ============================================================================
# SIGNAL OUTCOME TRACKING API
# ============================================================================

@app.get("/api/outcomes/stats", dependencies=[Depends(require_internal_key)])
def get_outcomes_stats(days: int = Query(default=30, ge=1, le=365)):
    """Get signal outcome statistics.
    
    Returns win/loss/pending counts and win rate.
    """
    from core.outcome_tracker import get_outcome_stats
    
    stats = get_outcome_stats(days=days)
    return {"ok": True, "days": days, **stats}


@app.get("/api/outcomes/{signal_id}", dependencies=[Depends(require_internal_key)])
def get_signal_outcome_api(signal_id: str):
    """Get outcome for a specific signal."""
    from core.outcome_tracker import get_signal_outcome
    
    outcome = get_signal_outcome(signal_id)
    if outcome:
        return {"ok": True, "signal_id": signal_id, "outcome": outcome}
    return {"ok": True, "signal_id": signal_id, "outcome": {"outcome": "PENDING"}}


@app.post("/api/outcomes/check", dependencies=[Depends(require_internal_key)])
def run_outcome_check_api():
    """Manually trigger outcome check for all pending signals.
    
    Note: Uses the market_cache singleton. If cache is empty, loads from file.
    """
    from core.outcome_tracker import run_outcome_check, get_outcome_stats
    from market_data_cache import market_cache
    
    result = run_outcome_check(market_cache)
    stats = get_outcome_stats(days=30)
    
    return {
        "ok": True, 
        **result,
        "stats": stats
    }


# ============================================================================
# USER STRATEGY & DETECTOR API ENDPOINTS
# ============================================================================

@app.get("/api/detectors")
async def list_detectors():
    """List all available detectors with metadata."""
    from detectors.registry import DETECTOR_REGISTRY, get_detector
    
    result = []
    for name in sorted(DETECTOR_REGISTRY.keys()):
        try:
            det = get_detector(name)
            if det:
                result.append({
                    "name": name,
                    "doc": det.get_doc() if hasattr(det, "get_doc") else "",
                    "params_schema": det.get_params_schema() if hasattr(det, "get_params_schema") else {},
                    "examples": det.get_examples() if hasattr(det, "get_examples") else [],
                })
        except Exception:
            result.append({"name": name, "doc": "", "params_schema": {}, "examples": []})
    
    return {"ok": True, "detectors": result, "count": len(result)}


@app.get("/api/presets")
async def list_presets():
    """List available strategy presets."""
    import glob
    presets = []
    for f in glob.glob("config/presets/*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.loads(fp.read())
                presets.append({
                    "preset_id": data.get("preset_id", Path(f).stem),
                    "strategies": data.get("strategies", []),
                })
        except Exception:
            pass
    return {"ok": True, "presets": presets, "count": len(presets)}


@app.post("/api/signals/{signal_id}/explain", dependencies=[Depends(require_internal_key)])
async def explain_signal(signal_id: str):
    """Generate AI explanation for a signal using OpenAI.
    
    Returns a detailed explanation in Mongolian about why this signal 
    was generated and what conditions were met.
    """
    import os
    
    # Find signal in history
    path = _signals_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="No signals history found")
    
    signal_data = None
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    sid = str(obj.get("signal_id") or obj.get("id") or "")
                    if sid == signal_id:
                        signal_data = obj
                        break
                except Exception:
                    continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading signals: {e}")
    
    if not signal_data:
        raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")
    
    # Check if OpenAI is available
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        # Return a basic explanation without AI
        return {
            "ok": True,
            "signal_id": signal_id,
            "explain_type": "basic",
            "explanation": _build_basic_explanation(signal_data),
        }
    
    # Use AI explainer
    try:
        from ai_explainer import explain_signal_ganbayar
        
        # Prepare signal dict for explainer
        explain_input = {
            "pair": signal_data.get("symbol", ""),
            "direction": signal_data.get("direction", ""),
            "timeframe": signal_data.get("tf") or signal_data.get("timeframe", "M5"),
            "entry": signal_data.get("entry", 0),
            "sl": signal_data.get("sl", 0),
            "tp": signal_data.get("tp", 0),
            "rr": signal_data.get("rr", 0),
            "context": {
                "h1_trend": signal_data.get("evidence", {}).get("h1_trend"),
                "h1_levels": signal_data.get("evidence", {}).get("h1_levels"),
                "detectors_triggered": signal_data.get("evidence", {}).get("detectors_triggered", []),
            }
        }
        
        ai_explanation = explain_signal_ganbayar(explain_input)
        
        return {
            "ok": True,
            "signal_id": signal_id,
            "explain_type": "ai",
            "explanation": ai_explanation,
            "signal_summary": {
                "symbol": signal_data.get("symbol"),
                "direction": signal_data.get("direction"),
                "entry": signal_data.get("entry"),
                "sl": signal_data.get("sl"),
                "tp": signal_data.get("tp"),
                "rr": signal_data.get("rr"),
            }
        }
    except Exception as e:
        # Fallback to basic explanation
        return {
            "ok": True,
            "signal_id": signal_id,
            "explain_type": "basic",
            "explanation": _build_basic_explanation(signal_data),
            "ai_error": str(e),
        }


def _build_basic_explanation(signal_data: dict) -> str:
    """Build a basic explanation without AI."""
    symbol = signal_data.get("symbol", "")
    direction = signal_data.get("direction", "")
    entry = signal_data.get("entry", 0)
    sl = signal_data.get("sl", 0)
    tp = signal_data.get("tp", 0)
    rr = signal_data.get("rr", 0)
    evidence = signal_data.get("evidence", {})
    detectors = evidence.get("detectors_triggered", [])
    
    lines = [
        f"📊 {symbol} - {direction} сигнал",
        "",
        f"Entry: {entry}",
        f"SL: {sl}",
        f"TP: {tp}",
        f"R:R: {rr:.2f}" if rr else "",
        "",
        "Илэрсэн нөхцлүүд:",
    ]
    
    if detectors:
        for d in detectors:
            lines.append(f"  • {d}")
    else:
        lines.append("  • Тодорхой detector бүртгэгдээгүй")
    
    return "\n".join(lines)


@app.get("/api/user/{user_id}/strategies")
async def get_user_strategies(user_id: str, api_key: str = Depends(require_internal_key)):
    """Get user's saved strategies."""
    from core.user_strategies_store import load_user_strategies
    
    strategies = load_user_strategies(user_id)
    return {"ok": True, "user_id": user_id, "strategies": strategies, "count": len(strategies)}


@app.post("/api/user/{user_id}/strategies")
async def save_user_strategies_endpoint(
    user_id: str,
    payload: dict = Body(...),
    api_key: str = Depends(require_internal_key)
):
    """Save user's strategies.
    
    Body: {"strategies": [...]}
    Each strategy should have:
      - strategy_id: unique name
      - enabled: true/false
      - detectors: ["detector1", "detector2", ...]
      - min_score: float (default 1.0)
      - min_rr: float (default 2.0)
      - allowed_regimes: ["RANGE", "TREND_BULL", "TREND_BEAR", "CHOP"]
    """
    from core.user_strategies_store import save_user_strategies
    
    strategies = payload.get("strategies", [])
    result = save_user_strategies(user_id, strategies)
    return result


@app.delete("/api/user/{user_id}/strategies")
async def delete_user_strategies(user_id: str, api_key: str = Depends(require_internal_key)):
    """Delete all user strategies."""
    from core.user_strategies_store import user_strategies_path
    
    path = user_strategies_path(user_id)
    try:
        path.unlink(missing_ok=True)
        return {"ok": True, "user_id": user_id, "deleted": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/user/{user_id}/strategies/from-preset/{preset_id}")
async def copy_preset_to_user(
    user_id: str,
    preset_id: str,
    api_key: str = Depends(require_internal_key)
):
    """Copy a preset to user's strategies."""
    from core.user_strategies_store import save_user_strategies
    
    preset_path = Path(f"config/presets/{preset_id}.json")
    if not preset_path.exists():
        raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found")
    
    try:
        with open(preset_path, "r", encoding="utf-8") as fp:
            data = json.loads(fp.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load preset: {e}")
    
    strategies = data.get("strategies", [])
    result = save_user_strategies(user_id, strategies)
    return result


# =========================
# Strategy Sharing (Public Library)
# =========================
SHARED_STRATEGIES_FILE = Path("data/shared_strategies.json")


def _load_shared_strategies() -> list[dict]:
    """Load all shared strategies from disk."""
    if not SHARED_STRATEGIES_FILE.exists():
        return []
    try:
        with open(SHARED_STRATEGIES_FILE, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_shared_strategies(strategies: list[dict]) -> bool:
    """Save shared strategies to disk."""
    try:
        SHARED_STRATEGIES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SHARED_STRATEGIES_FILE, "w", encoding="utf-8") as fp:
            json.dump(strategies, fp, indent=2, default=str)
        return True
    except Exception:
        return False


@app.get("/api/strategies/shared")
async def get_shared_strategies(
    api_key: str = Depends(require_internal_key)
):
    """Get all publicly shared strategies.
    
    Returns a list of strategies that users have shared with the community.
    """
    strategies = _load_shared_strategies()
    return {
        "ok": True,
        "strategies": strategies,
        "count": len(strategies),
    }


@app.post("/api/user/{user_id}/strategies/share")
async def share_strategy(
    user_id: str,
    payload: dict = Body(...),
    api_key: str = Depends(require_internal_key)
):
    """Share a strategy to the public library.
    
    Body: {
        "strategy_id": "my_strategy_name",
        "detectors": ["detector1", "detector2"],
        "min_score": 1.0,
        "min_rr": 2.0,
        "allowed_regimes": ["RANGE", "TREND_BULL"],
        "description": "Optional description of the strategy"
    }
    """
    strategy_id = payload.get("strategy_id") or payload.get("name") or ""
    if not strategy_id:
        raise HTTPException(status_code=400, detail="strategy_id required")
    
    detectors = payload.get("detectors", [])
    if not detectors or not isinstance(detectors, list):
        raise HTTPException(status_code=400, detail="detectors list required")
    
    # Build shared strategy entry
    shared_entry = {
        "share_id": f"{user_id}_{strategy_id}_{int(time.time())}",
        "strategy_id": strategy_id,
        "author_id": user_id,
        "detectors": detectors,
        "min_score": payload.get("min_score", 1.0),
        "min_rr": payload.get("min_rr", 2.0),
        "allowed_regimes": payload.get("allowed_regimes", ["RANGE", "TREND_BULL", "TREND_BEAR", "CHOP"]),
        "description": payload.get("description", ""),
        "shared_at": datetime.now(timezone.utc).isoformat(),
        "copies": 0,
        "rating": 0,
    }
    
    # Load existing, check for duplicates, append
    all_shared = _load_shared_strategies()
    
    # Remove any existing share by same user with same strategy_id
    all_shared = [s for s in all_shared if not (s.get("author_id") == user_id and s.get("strategy_id") == strategy_id)]
    
    all_shared.append(shared_entry)
    
    if not _save_shared_strategies(all_shared):
        raise HTTPException(status_code=500, detail="Failed to save shared strategy")
    
    return {
        "ok": True,
        "share_id": shared_entry["share_id"],
        "message": f"Strategy '{strategy_id}' shared successfully",
    }


@app.post("/api/user/{user_id}/strategies/import/{share_id}")
async def import_shared_strategy(
    user_id: str,
    share_id: str,
    api_key: str = Depends(require_internal_key)
):
    """Import a shared strategy to user's strategies.
    
    Copies the shared strategy into user's strategy list.
    """
    from core.user_strategies_store import load_user_strategies, save_user_strategies
    
    # Find the shared strategy
    all_shared = _load_shared_strategies()
    shared = next((s for s in all_shared if s.get("share_id") == share_id), None)
    
    if not shared:
        raise HTTPException(status_code=404, detail=f"Shared strategy '{share_id}' not found")
    
    # Load user's existing strategies
    user_strategies = load_user_strategies(user_id)
    
    # Create a copy with new ID (avoid conflicts)
    import_strategy = {
        "strategy_id": f"{shared['strategy_id']}_imported",
        "enabled": False,  # Start disabled so user can review
        "detectors": shared["detectors"],
        "min_score": shared.get("min_score", 1.0),
        "min_rr": shared.get("min_rr", 2.0),
        "allowed_regimes": shared.get("allowed_regimes", ["RANGE", "TREND_BULL", "TREND_BEAR", "CHOP"]),
        "imported_from": share_id,
        "original_author": shared.get("author_id"),
    }
    
    # Check if already imported
    existing = next((s for s in user_strategies if s.get("imported_from") == share_id), None)
    if existing:
        return {
            "ok": True,
            "already_imported": True,
            "strategy_id": existing.get("strategy_id"),
            "message": "Strategy already imported",
        }
    
    # Add to user's strategies
    user_strategies.append(import_strategy)
    result = save_user_strategies(user_id, user_strategies)
    
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail="Failed to import strategy")
    
    # Increment copies count on shared strategy
    for s in all_shared:
        if s.get("share_id") == share_id:
            s["copies"] = s.get("copies", 0) + 1
            break
    _save_shared_strategies(all_shared)
    
    return {
        "ok": True,
        "imported": True,
        "strategy_id": import_strategy["strategy_id"],
        "message": f"Strategy imported successfully",
    }


@app.delete("/api/user/{user_id}/strategies/shared/{share_id}")
async def delete_shared_strategy(
    user_id: str,
    share_id: str,
    api_key: str = Depends(require_internal_key)
):
    """Delete a strategy that user has shared.
    
    User can only delete their own shared strategies.
    """
    all_shared = _load_shared_strategies()
    
    # Find and verify ownership
    strategy = next((s for s in all_shared if s.get("share_id") == share_id), None)
    if not strategy:
        raise HTTPException(status_code=404, detail="Shared strategy not found")
    
    if strategy.get("author_id") != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own shared strategies")
    
    # Remove
    all_shared = [s for s in all_shared if s.get("share_id") != share_id]
    
    if not _save_shared_strategies(all_shared):
        raise HTTPException(status_code=500, detail="Failed to delete shared strategy")
    
    return {
        "ok": True,
        "deleted": True,
        "share_id": share_id,
    }


# =========================
# Telegram Connect Flow (v0.2)
# =========================
@app.post("/api/telegram/connect-url", dependencies=[Depends(require_internal_key)])
def telegram_connect_url(payload: dict):
    """Generate a Telegram deep link for user to connect their chat.
    
    Payload:
      - user_id: str (required)
    
    Returns:
      - ok: bool
      - url: str (deep link to open bot with start token)
    """
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    
    from core.event_queue import create_connect_token, init_db
    
    # Ensure DB exists
    try:
        init_db()
    except Exception:
        pass
    
    token = create_connect_token(user_id, expires_in_s=1800)  # 30 min
    if not token:
        raise HTTPException(status_code=500, detail="Failed to create connect token")
    
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "JKMCopilotBot")
    deep_link = f"https://t.me/{bot_username}?start={token}"
    
    return {"ok": True, "url": deep_link, "expires_in_s": 1800}


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, secret: str = ""):
    """Telegram webhook endpoint for /start connect flow.
    
    Query param:
      - secret: must match TELEGRAM_WEBHOOK_SECRET
    """
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not expected_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    if secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}  # Telegram expects 200 even on parse failure
    
    # Handle /start <token> message
    message = body.get("message", {})
    text = str(message.get("text") or "").strip()
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    
    if not chat_id:
        return {"ok": True}
    
    # Check for /start command with token
    if text.startswith("/start "):
        token = text[7:].strip()
        if token:
            from core.event_queue import validate_connect_token, init_db
            from user_db import set_telegram_chat
            
            try:
                init_db()
            except Exception:
                pass
            
            user_id = validate_connect_token(token)
            if user_id:
                # Bind chat_id to user
                set_telegram_chat(user_id, str(chat_id))
                
                # Send confirmation message
                try:
                    from services.notifier_telegram import telegram_notifier
                    telegram_notifier.send_message(
                        "✅ Telegram connected!\n\nТа одоо setup илэрсэн үед Telegram-аар мэдэгдэл хүлээн авах болно.",
                        chat_id=chat_id,
                    )
                except Exception:
                    pass
                
                return {"ok": True, "connected": True}
            else:
                # Invalid/expired token
                try:
                    from services.notifier_telegram import telegram_notifier
                    telegram_notifier.send_message(
                        "❌ Token expired or invalid.\n\nШинэ холболтын линк авна уу.",
                        chat_id=chat_id,
                    )
                except Exception:
                    pass
    
    return {"ok": True}


@app.get("/api/telegram/status/{user_id}", dependencies=[Depends(require_internal_key)])
def telegram_status(user_id: str):
    """Check Telegram connection status for a user."""
    from user_db import get_telegram_chat, get_telegram_enabled
    
    chat_id = get_telegram_chat(user_id)
    enabled = get_telegram_enabled(user_id)
    
    connected = bool(chat_id)
    # Mask chat_id for security (show only last 4 digits)
    masked_chat = f"***{str(chat_id)[-4:]}" if chat_id else None
    
    return {
        "ok": True,
        "user_id": user_id,
        "connected": connected,
        "enabled": enabled,
        "chat_id_masked": masked_chat,
    }


@app.post("/api/telegram/toggle/{user_id}", dependencies=[Depends(require_internal_key)])
def telegram_toggle(user_id: str, payload: dict):
    """Enable/disable Telegram notifications for a user.
    
    Payload:
      - enabled: bool
    """
    from user_db import set_telegram_enabled
    
    enabled = bool(payload.get("enabled", True))
    success = set_telegram_enabled(user_id, enabled)
    
    return {"ok": success, "user_id": user_id, "enabled": enabled}


# =========================
# Signal Detail Endpoint
# =========================


@app.get("/api/signals/{signal_id}")
def get_signal_detail(
    signal_id: str,
    user_id: str | None = Query(None, description="Optional user_id filter"),
):
    """Get a single signal by ID from signals.jsonl.
    
    Returns 404 if not found.
    """
    from core.signals_store import get_public_signal_by_id_jsonl
    
    uid = user_id.strip() if user_id else "system"
    include_all = not bool(user_id)
    
    result = get_public_signal_by_id_jsonl(
        user_id=uid,
        signal_id=signal_id,
        include_all_users=include_all,
    )
    
    if result is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "not_found"})
    
    return {"ok": True, "signal": result}


# =========================
# Symbols Endpoint
# =========================


@app.get("/api/symbols")
def get_symbols():
    """Return all tradeable symbols (canonical 15-symbol list)."""
    # Always return the canonical list for dashboard backtest
    CANONICAL_SYMBOLS = [
        "EURUSD", "USDJPY", "GBPUSD", "AUDUSD", "USDCAD",
        "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
        "AUDJPY", "EURAUD", "EURCHF", "XAUUSD", "BTCUSD",
    ]
    
    try:
        from watchlist_union import get_union_watchlist
        symbols = get_union_watchlist()
        if symbols and len(symbols) > 3:
            return {"ok": True, "symbols": symbols, "count": len(symbols)}
    except Exception:
        pass
    
    # Fallback: return canonical list
    return {"ok": True, "symbols": CANONICAL_SYMBOLS, "count": len(CANONICAL_SYMBOLS)}


# =========================
# Candles Endpoint for Charts
# =========================


@app.get("/api/markets/{symbol}/candles")
def get_candles(
    symbol: str,
    tf: str = Query("M5", description="Timeframe: M5, M15, H1, H4, D1"),
    limit: int = Query(500, ge=1, le=2000),
):
    """Return candles for chart rendering.
    
    Returns list of {time: epoch_sec, open, high, low, close}.
    """
    from market_data_cache import market_cache
    
    sym = symbol.strip().upper()
    timeframe = tf.strip().upper()
    
    try:
        raw_candles = market_cache.get_resampled(sym, timeframe)
    except Exception:
        raw_candles = []
    
    if not raw_candles:
        return {"ok": True, "symbol": sym, "tf": timeframe, "candles": [], "count": 0}
    
    # Convert to output format with epoch time
    out = []
    for c in raw_candles[-limit:]:
        t = c.get("time")
        epoch: int = 0
        if isinstance(t, datetime):
            epoch = int(t.timestamp())
        elif isinstance(t, (int, float)):
            epoch = int(t)
        elif isinstance(t, str):
            try:
                dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                epoch = int(dt.timestamp())
            except Exception:
                continue
        
        try:
            out.append({
                "time": epoch,
                "open": float(c.get("open", 0)),
                "high": float(c.get("high", 0)),
                "low": float(c.get("low", 0)),
                "close": float(c.get("close", 0)),
            })
        except Exception:
            continue
    
    return {"ok": True, "symbol": sym, "tf": timeframe, "candles": out, "count": len(out)}


# =========================
# Metrics Endpoint
# =========================


@app.get("/api/metrics")
def get_metrics():
    """Return simple signal metrics for dashboard cards."""
    path = _signals_path()
    
    if not path.exists():
        return {
            "ok": True,
            "total_signals": 0,
            "ok_count": 0,
            "none_count": 0,
            "hit_rate": None,
            "last_24h_ok": 0,
            "last_24h_total": 0,
        }
    
    total_signals = 0
    ok_count = 0
    none_count = 0
    last_24h_ok = 0
    last_24h_total = 0
    
    now_ts = int(time.time())
    cutoff_24h = now_ts - 86400
    
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                
                total_signals += 1
                status = str(obj.get("status") or "").upper()
                
                if status == "OK":
                    ok_count += 1
                elif status == "NONE":
                    none_count += 1
                
                # Check timestamp for 24h window
                ts = obj.get("ts") or obj.get("created_at")
                sig_ts = 0
                if isinstance(ts, (int, float)):
                    sig_ts = int(ts)
                elif isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        sig_ts = int(dt.timestamp())
                    except Exception:
                        pass
                
                if sig_ts >= cutoff_24h:
                    last_24h_total += 1
                    if status == "OK":
                        last_24h_ok += 1
    except Exception:
        pass
    
    hit_rate = None
    denom = ok_count + none_count
    if denom > 0:
        hit_rate = round(ok_count / denom, 4)
    
    return {
        "ok": True,
        "total_signals": total_signals,
        "ok_count": ok_count,
        "none_count": none_count,
        "hit_rate": hit_rate,
        "last_24h_ok": last_24h_ok,
        "last_24h_total": last_24h_total,
    }


@app.get("/api/metrics/detailed")
def get_detailed_metrics():
    """Return detailed performance metrics broken down by symbol, timeframe, and day."""
    path = _signals_path()
    
    if not path.exists():
        return {
            "ok": True,
            "total_signals": 0,
            "by_symbol": {},
            "by_timeframe": {},
            "by_day": [],
            "by_direction": {"BUY": {"ok": 0, "none": 0}, "SELL": {"ok": 0, "none": 0}},
        }
    
    from collections import defaultdict
    
    total_signals = 0
    by_symbol: dict = defaultdict(lambda: {"ok": 0, "none": 0, "total": 0})
    by_tf: dict = defaultdict(lambda: {"ok": 0, "none": 0, "total": 0})
    by_day: dict = defaultdict(lambda: {"ok": 0, "none": 0, "total": 0})
    by_direction: dict = {"BUY": {"ok": 0, "none": 0}, "SELL": {"ok": 0, "none": 0}}
    
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                
                total_signals += 1
                status = str(obj.get("status") or "").upper()
                symbol = str(obj.get("symbol") or "UNKNOWN")
                tf = str(obj.get("tf") or obj.get("timeframe") or "M5")
                direction = str(obj.get("direction") or "NA").upper()
                
                # Parse timestamp for day grouping
                ts = obj.get("ts") or obj.get("created_at")
                day_str = "unknown"
                if isinstance(ts, (int, float)):
                    day_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                elif isinstance(ts, str):
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        day_str = dt.strftime("%Y-%m-%d")
                    except Exception:
                        pass
                
                # By symbol
                by_symbol[symbol]["total"] += 1
                if status == "OK":
                    by_symbol[symbol]["ok"] += 1
                elif status == "NONE":
                    by_symbol[symbol]["none"] += 1
                
                # By timeframe
                by_tf[tf]["total"] += 1
                if status == "OK":
                    by_tf[tf]["ok"] += 1
                elif status == "NONE":
                    by_tf[tf]["none"] += 1
                
                # By day
                by_day[day_str]["total"] += 1
                if status == "OK":
                    by_day[day_str]["ok"] += 1
                elif status == "NONE":
                    by_day[day_str]["none"] += 1
                
                # By direction
                if direction in by_direction:
                    if status == "OK":
                        by_direction[direction]["ok"] += 1
                    elif status == "NONE":
                        by_direction[direction]["none"] += 1
    except Exception:
        pass
    
    # Convert by_day to sorted list for charting
    day_list = []
    for day, stats in sorted(by_day.items()):
        if day == "unknown":
            continue
        hit_rate = None
        denom = stats["ok"] + stats["none"]
        if denom > 0:
            hit_rate = round(stats["ok"] / denom, 4)
        day_list.append({
            "date": day,
            "ok": stats["ok"],
            "none": stats["none"],
            "total": stats["total"],
            "hit_rate": hit_rate,
        })
    
    # Add hit_rate to by_symbol
    symbol_stats = {}
    for sym, stats in by_symbol.items():
        denom = stats["ok"] + stats["none"]
        hit_rate = round(stats["ok"] / denom, 4) if denom > 0 else None
        symbol_stats[sym] = {**stats, "hit_rate": hit_rate}
    
    # Add hit_rate to by_tf
    tf_stats = {}
    for tf, stats in by_tf.items():
        denom = stats["ok"] + stats["none"]
        hit_rate = round(stats["ok"] / denom, 4) if denom > 0 else None
        tf_stats[tf] = {**stats, "hit_rate": hit_rate}
    
    return {
        "ok": True,
        "total_signals": total_signals,
        "by_symbol": symbol_stats,
        "by_timeframe": tf_stats,
        "by_day": day_list[-30:],  # Last 30 days
        "by_direction": by_direction,
    }


# =========================
# WebSocket Signals Real-time Endpoint
# =========================
class SignalsBroadcaster:
    """Manages WebSocket connections and broadcasts new signals."""
    
    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            self._connections.discard(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        async with self._lock:
            dead = set()
            for ws in self._connections:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.add(ws)
            self._connections -= dead
    
    @property
    def connection_count(self) -> int:
        return len(self._connections)


signals_broadcaster = SignalsBroadcaster()


@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    """WebSocket endpoint for real-time signal updates.
    
    Clients connect and receive:
    - Initial batch of recent signals
    - New signals as they are generated
    - Heartbeat pings every 30 seconds
    """
    await signals_broadcaster.connect(websocket)
    
    try:
        # Send recent signals on connect
        from signals_tracker import _load_signals
        try:
            all_signals = _load_signals()
            recent = all_signals[-50:] if len(all_signals) > 50 else all_signals
            await websocket.send_json({
                "type": "initial",
                "signals": recent,
                "total": len(all_signals),
            })
        except Exception:
            await websocket.send_json({"type": "initial", "signals": [], "total": 0})
        
        # Keep connection alive with heartbeat + listen for client messages
        last_count = len(all_signals) if 'all_signals' in dir() else 0
        
        while True:
            # Check for new signals every 5 seconds
            await asyncio.sleep(5)
            
            try:
                current_signals = _load_signals()
                current_count = len(current_signals)
                
                if current_count > last_count:
                    # New signals detected - send them
                    new_signals = current_signals[last_count:]
                    await websocket.send_json({
                        "type": "new_signals",
                        "signals": new_signals,
                        "total": current_count,
                    })
                    last_count = current_count
                
                # Send heartbeat every iteration
                await websocket.send_json({"type": "heartbeat", "ts": int(time.time())})
                
            except Exception:
                # If signal loading fails, just continue
                await websocket.send_json({"type": "heartbeat", "ts": int(time.time())})
                
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await signals_broadcaster.disconnect(websocket)


@app.get("/api/ws/status")
def get_ws_status():
    """Get WebSocket connection status."""
    return {
        "ok": True,
        "active_connections": signals_broadcaster.connection_count,
    }


# ============================================================================
# STRATEGY SIMULATOR API - Main simulation endpoint
# ============================================================================

@app.post("/api/strategy-sim/run", dependencies=[Depends(require_internal_key)])
async def run_strategy_simulator(payload: dict = Body(...)):
    """
    Run strategy simulation on historical data.
    
    This is the main strategy testing endpoint that:
    - Loads historical candles for the specified time range
    - Runs detectors WITHOUT lookahead (entry at next bar)
    - Simulates trades with SL/TP outcomes
    - Returns metrics and trade list
    
    Request body:
    {
        "user_id": "string|null",
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "range": {
            "mode": "PRESET" | "CUSTOM",
            "preset": "7D" | "30D" | "90D" | "6M" | "1Y",
            "from_ts": number|null,
            "to_ts": number|null
        },
        "strategy_id": "string",
        "assumptions": {
            "intrabar_policy": "SL_FIRST",
            "spread": 0,
            "slippage": 0,
            "commission": 0,
            "max_trades": 1000
        }
    }
    
    Response:
    {
        "ok": true,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "from_ts": 1234567890,
        "to_ts": 1234567890,
        "strategy_id": "my_strategy",
        "summary": {
            "entries": 25,
            "tp_hits": 15,
            "sl_hits": 10,
            "winrate": 60.0,
            "avg_r": 1.2,
            "profit_factor": 1.8,
            "avg_duration_bars": 12.5,
            "total_r": 30.0
        },
        "trades": [...],
        "warnings": []
    }
    """
    from core.strategy_simulator import SimulatorRequest, run_simulation
    
    try:
        request = SimulatorRequest.from_dict(payload)
        response = run_simulation(request)
        return response.to_dict()
    except Exception as e:
        import traceback
        return {
            "ok": False,
            "error": {
                "code": "SIMULATION_ERROR",
                "message": str(e),
                "details": {"trace": traceback.format_exc()},
            },
        }


@app.get("/api/strategy-sim/symbols", dependencies=[Depends(require_internal_key)])
async def get_simulator_symbols():
    """Get available symbols from cache for simulator."""
    cache_path = Path("state/market_cache.json")
    if not cache_path.exists():
        return {"ok": False, "error": "Cache not found", "symbols": []}
    
    try:
        with open(cache_path, "r") as f:
            cache = json.load(f)
        symbols_data = cache.get("symbols", cache)
        symbols = [k for k in symbols_data.keys() if k not in ("version",)]
        return {"ok": True, "symbols": sorted(symbols)}
    except Exception as e:
        return {"ok": False, "error": str(e), "symbols": []}


# ============================================================================
# STRATEGY TESTER API ENDPOINTS (Legacy - deprecated, use /api/strategy-sim/run)
# ============================================================================

@app.post("/api/strategy-tester/run", dependencies=[Depends(require_internal_key)])
async def run_strategy_tester(payload: dict = Body(...)):
    """
    [DEPRECATED] Use /api/strategy-sim/run instead.
    
    Run a strategy test with the configured detectors.
    
    Request body:
    {
        "symbol": "XAUUSD",
        "detectors": ["pinbar_at_level", "break_retest"],
        "entry_tf": "M15",
        "trend_tf": "H4",
        "start_date": "2024-01-01",  // optional
        "end_date": "2024-12-31",    // optional
        "spread_pips": 1.0,
        "slippage_pips": 0.5,
        "commission_per_trade": 0.0,
        "initial_capital": 10000.0,
        "risk_per_trade_pct": 1.0,
        "intrabar_policy": "sl_first",  // sl_first, tp_first, bar_magnifier, random
        "min_rr": 2.0,
        "min_score": 1.0,
        "max_trades_per_day": 10,
        "max_bars_in_trade": 100
    }
    
    Returns:
    {
        "ok": true,
        "run_id": "...",
        "status": "completed",
        "metrics": {...},
        "trade_count": 25,
        "duration_seconds": 1.5
    }
    """
    import time
    import uuid
    from core.strategy_tester import TesterConfig, IntrabarPolicy
    from core.strategy_tester.storage import TesterStorage
    from detectors.registry import DETECTOR_REGISTRY
    
    try:
        symbol = payload.get("symbol", "XAUUSD")
        detectors_list = payload.get("detectors", ["pinbar_at_level"])
        entry_tf = payload.get("entry_tf", "M15")
        
        # Validate detectors exist
        valid_detectors = [d for d in detectors_list if d in DETECTOR_REGISTRY]
        if not valid_detectors:
            return {"ok": False, "error": f"No valid detectors found. Available: {list(DETECTOR_REGISTRY.keys())[:5]}..."}
        
        # Build config
        intrabar_str = payload.get("intrabar_policy", "sl_first")
        try:
            intrabar_policy = IntrabarPolicy(intrabar_str)
        except:
            intrabar_policy = IntrabarPolicy.SL_FIRST
        
        config = TesterConfig(
            detectors=valid_detectors,
            symbol=symbol,
            entry_tf=entry_tf,
            trend_tf=payload.get("trend_tf", "H4"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            spread_pips=float(payload.get("spread_pips", 1.0)),
            slippage_pips=float(payload.get("slippage_pips", 0.5)),
            commission_per_trade=float(payload.get("commission_per_trade", 0.0)),
            initial_capital=float(payload.get("initial_capital", 10000.0)),
            risk_per_trade_pct=float(payload.get("risk_per_trade_pct", 1.0)),
            intrabar_policy=intrabar_policy,
            min_rr=float(payload.get("min_rr", 2.0)),
            min_score=float(payload.get("min_score", 1.0)),
            max_trades_per_day=int(payload.get("max_trades_per_day", 10)),
            max_bars_in_trade=int(payload.get("max_bars_in_trade", 100)),
        )
        
        # Load candle data from cache
        candles = []
        cache_path = Path("state/market_cache.json")
        if cache_path.exists():
            with open(cache_path, "r") as f:
                cache = json.load(f)
            
            # Cache format: {"version": 1, "symbols": {"XAUUSD": [candles], ...}}
            symbols_data = cache.get("symbols", cache)  # fallback to old format
            raw_candles = symbols_data.get(symbol, [])
            
            # Handle if symbols_data[symbol] is dict with timeframes (old format)
            if isinstance(raw_candles, dict):
                raw_candles = raw_candles.get(entry_tf, raw_candles.get("M5", []))
                if not raw_candles:
                    for tf_key in ["M5", "M15", "H1", "H4"]:
                        if raw_candles.get(tf_key):
                            raw_candles = raw_candles[tf_key]
                            break
            
            for c in raw_candles:
                candles.append({
                    "time": c.get("time", c.get("t", 0)),
                    "open": c.get("open", c.get("o", 0)),
                    "high": c.get("high", c.get("h", 0)),
                    "low": c.get("low", c.get("l", 0)),
                    "close": c.get("close", c.get("c", 0)),
                    "volume": c.get("volume", c.get("v", 0)),
                })
        
        if len(candles) < 50:
            return {"ok": False, "error": f"Insufficient data for {symbol}, need at least 50 candles, got {len(candles)}"}
        
        # Generate run_id and save basic run info
        run_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        # For now, return a simple test result
        # Full detector integration will be added later
        duration = time.time() - start_time
        
        result = {
            "ok": True,
            "run_id": run_id,
            "status": "completed",
            "error": None,
            "trade_count": 0,
            "candle_count": len(candles),
            "detectors_used": valid_detectors,
            "metrics": {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "total_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
            },
            "duration_seconds": round(duration, 3),
            "config": {
                "symbol": symbol,
                "entry_tf": entry_tf,
                "detectors": valid_detectors,
                "initial_capital": config.initial_capital,
                "min_rr": config.min_rr,
            },
            "message": f"Strategy test initialized with {len(valid_detectors)} detectors and {len(candles)} candles. Full simulation coming soon.",
        }
        
        # Save to storage
        storage = TesterStorage()
        storage.save_simple(run_id, result)
        
        return result
        
    except Exception as e:
        import traceback
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}


@app.get("/api/strategy-tester/runs", dependencies=[Depends(require_internal_key)])
async def list_tester_runs(limit: int = 50, offset: int = 0):
    """List all test runs."""
    from core.strategy_tester import TesterStorage
    
    storage = TesterStorage()
    runs = storage.list_runs(limit=limit, offset=offset)
    
    return {
        "ok": True,
        "runs": runs,
        "count": len(runs),
    }


@app.get("/api/strategy-tester/runs/{run_id}", dependencies=[Depends(require_internal_key)])
async def get_tester_run(run_id: str):
    """Get a specific test run with full details."""
    from core.strategy_tester import TesterStorage
    
    storage = TesterStorage()
    run = storage.load(run_id)
    
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    return {
        "ok": True,
        "run": run.to_full_dict(),
    }


@app.get("/api/strategy-tester/runs/{run_id}/trades", dependencies=[Depends(require_internal_key)])
async def get_tester_run_trades(run_id: str):
    """Get trades for a specific test run."""
    from core.strategy_tester import TesterStorage
    
    storage = TesterStorage()
    trades = storage.get_trades(run_id)
    
    return {
        "ok": True,
        "trades": trades,
        "count": len(trades),
    }


@app.get("/api/strategy-tester/runs/{run_id}/equity", dependencies=[Depends(require_internal_key)])
async def get_tester_run_equity(run_id: str):
    """Get equity curve for a specific test run."""
    from core.strategy_tester import TesterStorage
    
    storage = TesterStorage()
    equity = storage.get_equity_curve(run_id)
    
    return {
        "ok": True,
        "equity_curve": equity,
        "count": len(equity),
    }


@app.delete("/api/strategy-tester/runs/{run_id}", dependencies=[Depends(require_internal_key)])
async def delete_tester_run(run_id: str):
    """Delete a test run."""
    from core.strategy_tester import TesterStorage
    
    storage = TesterStorage()
    success = storage.delete(run_id)
    
    return {
        "ok": success,
        "deleted": run_id if success else None,
    }
