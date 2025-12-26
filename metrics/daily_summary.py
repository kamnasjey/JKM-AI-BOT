from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.atomic_io import atomic_write_text


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, str) and v.strip().upper() == "NA":
        return None
    try:
        return float(v)
    except Exception:
        return None


def _safe_str(v: Any) -> str:
    s = str(v if v is not None else "NA").strip()
    return s if s else "NA"


def read_events_jsonl(path: str, *, since_ts: Optional[float] = None, max_lines: int = 50000) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []

    out: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= int(max_lines):
                    break
                s = (line or "").strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                if since_ts is not None:
                    try:
                        ts = float(obj.get("ts"))
                    except Exception:
                        ts = None
                    if ts is None or ts < float(since_ts):
                        continue
                out.append(obj)
    except Exception:
        return []

    return out


@dataclass(frozen=True)
class DailySummary:
    date: str
    window_hours: int
    total_pairs: int
    ok_count: int
    ok_rate: float
    top_reasons: List[Dict[str, Any]]
    top_strategies_by_ok: List[Dict[str, Any]]
    avg_score: Optional[float]
    avg_rr: Optional[float]
    cooldown_blocks: int
    daily_limit_blocks: int
    regimes: List[Dict[str, Any]]

    # Coverage (backward compatible additions)
    detector_hit_counts: Dict[str, int] = field(default_factory=dict)
    detector_hit_rates: Dict[str, float] = field(default_factory=dict)
    top_detectors: List[Dict[str, Any]] = field(default_factory=list)
    per_strategy_top_detectors: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    dead_detectors: List[str] = field(default_factory=list)

    # Dead detector diagnosis (deterministic, rule-based)
    dead_diagnosis: Dict[str, List[str]] = field(default_factory=dict)
    dead_diagnosis_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Compact coverage (for one-line logs / Telegram)
    per_strategy_top_detectors_compact: Dict[str, List[str]] = field(default_factory=dict)
    total_strategies_covered: int = 0
    loaded_detectors: int = 0
    seen_detectors: int = 0
    dead_detectors_count: int = 0

    # Shadow coverage (optional; when events include shadow_hits)
    shadow_detector_hit_counts: Dict[str, int] = field(default_factory=dict)
    shadow_top_detectors: List[Dict[str, Any]] = field(default_factory=list)
    shadow_dead_detectors: List[str] = field(default_factory=list)
    shadow_seen_detectors: int = 0
    shadow_dead_detectors_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "window_hours": int(self.window_hours),
            "total_pairs": int(self.total_pairs),
            "ok_count": int(self.ok_count),
            "ok_rate": float(self.ok_rate),
            "top_reasons": list(self.top_reasons),
            "top_strategies_by_ok": list(self.top_strategies_by_ok),
            "avg_score": self.avg_score,
            "avg_rr": self.avg_rr,
            "cooldown_blocks": int(self.cooldown_blocks),
            "daily_limit_blocks": int(self.daily_limit_blocks),
            "regimes": list(self.regimes),
            "detector_hit_counts": dict(self.detector_hit_counts),
            "detector_hit_rates": dict(self.detector_hit_rates),
            "top_detectors": list(self.top_detectors),
            "per_strategy_top_detectors": dict(self.per_strategy_top_detectors),
            "dead_detectors": list(self.dead_detectors),
            "dead_diagnosis": dict(self.dead_diagnosis),
            "dead_diagnosis_details": dict(self.dead_diagnosis_details),
            "per_strategy_top_detectors_compact": dict(self.per_strategy_top_detectors_compact),
            "total_strategies_covered": int(self.total_strategies_covered),
            "loaded_detectors": int(self.loaded_detectors),
            "seen_detectors": int(self.seen_detectors),
            "dead_detectors_count": int(self.dead_detectors_count),
            "shadow_detector_hit_counts": dict(self.shadow_detector_hit_counts),
            "shadow_top_detectors": list(self.shadow_top_detectors),
            "shadow_dead_detectors": list(self.shadow_dead_detectors),
            "shadow_seen_detectors": int(self.shadow_seen_detectors),
            "shadow_dead_detectors_count": int(self.shadow_dead_detectors_count),
        }


def _coerce_str_list(v: Any, *, max_items: int = 10) -> List[str]:
    if not isinstance(v, list):
        return []
    out: List[str] = []
    for x in v[: int(max_items)]:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _loaded_detector_names() -> List[str]:
    try:
        from engines.detectors.registry import detector_registry, ensure_registry_loaded

        ensure_registry_loaded(logger=None, custom_dir="detectors/custom")
        names = detector_registry.list_detectors() or []
        return sorted([str(x) for x in names if str(x or "").strip()])
    except Exception:
        return []


def _build_registry_meta(names: List[str]) -> Dict[str, Dict[str, Any]]:
    """Build minimal detector metadata needed for dead-detector diagnosis."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        from engines.detectors.registry import detector_registry

        for name in names or []:
            n = str(name or "").strip()
            if not n:
                continue
            cls = detector_registry.get_detector_class(n)
            if cls is None:
                continue
            try:
                inst = cls(config={"enabled": True})
                meta = getattr(inst, "meta", None)
                supported = getattr(meta, "supported_regimes", None)
                family = getattr(meta, "family", None)
                param_schema = getattr(meta, "param_schema", None)
                out[n] = {
                    "supported_regimes": sorted([str(x) for x in (supported or []) if str(x or "").strip()]),
                    "family": str(family or ""),
                    "param_schema": (dict(param_schema) if isinstance(param_schema, dict) else {}),
                }
            except Exception:
                # Best-effort meta; skip if instantiation fails.
                continue
    except Exception:
        return {}
    return out


def _load_strategy_specs_for_diagnosis() -> List[Any]:
    """Best-effort load enabled strategy specs from default pack."""
    try:
        from strategies.loader import load_strategies

        return list(load_strategies("config/strategies.json") or [])
    except Exception:
        return []


def _compact_per_strategy_top_detectors(
    per_strategy: Dict[str, Counter],
    *,
    max_strategies: int = 3,
    max_detectors: int = 3,
) -> Dict[str, List[str]]:
    """Return compact mapping: {strategy_id: ["det:count", ...]}.

    Deterministic: sort by total hits desc, then strategy_id.
    """
    rows: List[tuple[str, int]] = []
    for sid, ctr in (per_strategy or {}).items():
        if not isinstance(ctr, Counter):
            continue
        total = int(sum(int(v) for v in ctr.values()))
        if total <= 0:
            continue
        rows.append((str(sid), total))
    rows.sort(key=lambda x: (-int(x[1]), x[0]))

    out: Dict[str, List[str]] = {}
    for sid, _total in rows[: int(max_strategies)]:
        ctr = per_strategy.get(sid) or Counter()
        items = []
        for det, c in ctr.most_common(int(max_detectors)):
            d = str(det or "").strip()
            if not d:
                continue
            items.append(f"{d}:{int(c)}")
        out[str(sid)] = items
    return out


def summarize_events(events: Iterable[Dict[str, Any]], *, date: str, window_hours: int = 24) -> DailySummary:
    total = 0
    ok = 0

    none_reasons = Counter()
    ok_by_strategy = Counter()
    regimes = Counter()

    score_sum = 0.0
    score_n = 0
    rr_sum = 0.0
    rr_n = 0

    cooldown_blocks = 0
    daily_limit_blocks = 0

    detector_hit_counts = Counter()
    shadow_detector_hit_counts = Counter()
    detector_hit_by_strategy_ok: Dict[str, Counter] = {}

    for ev in events:
        if not isinstance(ev, dict):
            continue
        total += 1

        status = _safe_str(ev.get("status")).upper()
        reason = _safe_str(ev.get("reason")).upper()
        strategy_id = _safe_str(ev.get("strategy_id"))
        regime = _safe_str(ev.get("regime")).upper()
        if regime != "NA":
            regimes[regime] += 1

        if status == "OK":
            ok += 1
            ok_by_strategy[strategy_id] += 1

            sc = _safe_float(ev.get("score"))
            if sc is not None:
                score_sum += float(sc)
                score_n += 1

            rr = _safe_float(ev.get("rr"))
            if rr is not None:
                rr_sum += float(rr)
                rr_n += 1

            # Coverage: count detector hits from OK events only.
            top_hits = _coerce_str_list(ev.get("top_hits"), max_items=10)
            if top_hits:
                for det in top_hits:
                    detector_hit_counts[det] += 1
                    if strategy_id not in detector_hit_by_strategy_ok:
                        detector_hit_by_strategy_ok[strategy_id] = Counter()
                    detector_hit_by_strategy_ok[strategy_id][det] += 1
        else:
            none_reasons[reason] += 1

            if reason == "COOLDOWN_ACTIVE":
                cooldown_blocks += 1
            if reason == "DAILY_LIMIT_REACHED":
                daily_limit_blocks += 1

        # Note: NONE events may carry top_hits (best-side contribs), but coverage
        # metrics intentionally focus on realized OK hits for tuning stability.

        # Shadow coverage (optional): when SHADOW_ALL_DETECTORS=1 the runtime may
        # emit shadow_hits for coverage-only evaluation.
        shadow_hits = _coerce_str_list(ev.get("shadow_hits"), max_items=50)
        if shadow_hits:
            for det in shadow_hits:
                shadow_detector_hit_counts[det] += 1

    top_reasons = [
        {"reason": r, "count": int(c)} for r, c in none_reasons.most_common(8)
    ]
    top_strategies = [
        {"strategy_id": sid, "ok_count": int(c)} for sid, c in ok_by_strategy.most_common(8)
    ]
    top_regimes = [{"regime": r, "count": int(c)} for r, c in regimes.most_common(8)]

    ok_rate = float(ok) / float(total) if total > 0 else 0.0
    avg_score = (score_sum / float(score_n)) if score_n > 0 else None
    avg_rr = (rr_sum / float(rr_n)) if rr_n > 0 else None

    # Coverage summary
    top_detectors: List[Dict[str, Any]] = []
    denom_ok = int(ok)
    for det, c in detector_hit_counts.most_common(10):
        rate = (float(c) / float(denom_ok)) if denom_ok > 0 else 0.0
        top_detectors.append({"detector": str(det), "count": int(c), "rate": float(rate)})

    per_strategy_top: Dict[str, List[Dict[str, Any]]] = {}
    for sid, ctr in detector_hit_by_strategy_ok.items():
        per_strategy_top[str(sid)] = [
            {"detector": str(det), "count": int(c)} for det, c in ctr.most_common(5)
        ]

    loaded = _loaded_detector_names()
    dead = [d for d in loaded if detector_hit_counts.get(d, 0) <= 0]

    shadow_dead = [d for d in loaded if shadow_detector_hit_counts.get(d, 0) <= 0]

    shadow_top_detectors: List[Dict[str, Any]] = []
    denom_total = int(total)
    for det, c in shadow_detector_hit_counts.most_common(10):
        rate = (float(c) / float(denom_total)) if denom_total > 0 else 0.0
        shadow_top_detectors.append({"detector": str(det), "count": int(c), "rate": float(rate)})

    # Dead detector diagnosis (deterministic; best-effort)
    dead_diagnosis_details: Dict[str, Dict[str, Any]] = {}
    dead_diagnosis: Dict[str, List[str]] = {}
    try:
        from metrics.dead_detector_diagnosis import compact_dead_diagnosis, diagnose_dead_detectors

        strategy_specs = _load_strategy_specs_for_diagnosis()
        registry_meta = _build_registry_meta(loaded)
        details_all = diagnose_dead_detectors(
            dead_list=list(dead),
            strategies_specs=strategy_specs,
            registry_meta=registry_meta,
            window_stats={
                "date": str(date),
                "window_hours": int(window_hours),
                "ok": int(ok),
                "total": int(total),
            },
        )

        # Keep details bounded for report file size.
        dead_diagnosis_details = {
            det: dict(details_all.get(det) or {})
            for det in sorted(list(details_all.keys()))[:20]
            if isinstance(details_all.get(det), dict)
        }
        dead_diagnosis = compact_dead_diagnosis(dead_diagnosis_details, limit=5)
    except Exception:
        dead_diagnosis_details = {}
        dead_diagnosis = {}

    detector_hit_rates: Dict[str, float] = {}
    if denom_ok > 0:
        for det, c in detector_hit_counts.items():
            detector_hit_rates[str(det)] = float(c) / float(denom_ok)

    per_strategy_compact = _compact_per_strategy_top_detectors(
        detector_hit_by_strategy_ok,
        max_strategies=3,
        max_detectors=3,
    )
    total_strategies_covered = int(len([k for k, v in detector_hit_by_strategy_ok.items() if sum(v.values()) > 0]))

    return DailySummary(
        date=str(date),
        window_hours=int(window_hours),
        total_pairs=int(total),
        ok_count=int(ok),
        ok_rate=float(ok_rate),
        top_reasons=top_reasons,
        top_strategies_by_ok=top_strategies,
        avg_score=avg_score,
        avg_rr=avg_rr,
        cooldown_blocks=int(cooldown_blocks),
        daily_limit_blocks=int(daily_limit_blocks),
        regimes=top_regimes,
        detector_hit_counts={str(k): int(v) for k, v in detector_hit_counts.items()},
        detector_hit_rates={str(k): float(v) for k, v in detector_hit_rates.items()},
        top_detectors=top_detectors,
        per_strategy_top_detectors=per_strategy_top,
        dead_detectors=list(dead),
        dead_diagnosis=dict(dead_diagnosis),
        dead_diagnosis_details=dict(dead_diagnosis_details),
        per_strategy_top_detectors_compact=per_strategy_compact,
        total_strategies_covered=int(total_strategies_covered),
        loaded_detectors=int(len(loaded)),
        seen_detectors=int(len([k for k, v in detector_hit_counts.items() if int(v) > 0])),
        dead_detectors_count=int(len(dead)),
        shadow_detector_hit_counts={str(k): int(v) for k, v in shadow_detector_hit_counts.items()},
        shadow_top_detectors=list(shadow_top_detectors),
        shadow_dead_detectors=list(shadow_dead),
        shadow_seen_detectors=int(len([k for k, v in shadow_detector_hit_counts.items() if int(v) > 0])),
        shadow_dead_detectors_count=int(len(shadow_dead)),
    )


def summarize_last_24h(
    *,
    events_path: str = "state/metrics_events.jsonl",
    now_ts: Optional[float] = None,
) -> DailySummary:
    now = float(now_ts) if now_ts is not None else float(time.time())
    since = now - 24.0 * 3600.0
    date = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    events = read_events_jsonl(events_path, since_ts=since)
    return summarize_events(events, date=date, window_hours=24)


def write_daily_report(summary: DailySummary, *, out_dir: str = "state/metrics_daily") -> str:
    path = Path(out_dir) / f"{summary.date}.json"
    atomic_write_text(path, json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return str(path)


def format_tuning_report(
    summary_dict: Dict[str, Any],
    *,
    alert_codes: Iterable[str],
    max_items: int = 3,
) -> Dict[str, Any]:
    """Build a deterministic admin-only tuning report message.

    Returns dict with:
      - text
      - actions_count
      - patch_preview (optional)
    """
    from metrics.recommendations import format_tuning_suggestions, generate_recommendations, save_patch_suggestions

    date = str(summary_dict.get("date") or "NA")

    strategies_json: Optional[Dict[str, Any]] = None
    try:
        # Repository default location for strategy pack.
        with open("config/strategies.json", "r", encoding="utf-8") as f:
            strategies_json = json.load(f)
    except Exception:
        strategies_json = None

    recos = generate_recommendations(
        summary_dict,
        alert_codes=set(alert_codes or []),
        strategies_json=strategies_json,
    )

    # Persist patch suggestions for safe apply workflow (non-fatal).
    try:
        if strategies_json is not None and isinstance(strategies_json, dict):
            save_patch_suggestions(
                out_path="state/patch_suggestions.json",
                date=date,
                strategies_json=strategies_json,
                recommendations=list(recos),
            )
    except Exception:
        pass

    text = format_tuning_suggestions(date=date, recommendations=recos, max_items=max_items)
    actions_count = 0
    patch_preview = ""
    try:
        for r in recos:
            actions_count += len(getattr(r, "actions", []) or [])
        # Take patch preview from the highest-priority recommendation that has one.
        for r in recos:
            pv = str(getattr(r, "patch_preview", "") or "")
            if pv:
                patch_preview = pv
                break
    except Exception:
        actions_count = 0
        patch_preview = ""

    return {
        "text": text,
        "actions_count": int(actions_count),
        "patch_preview": patch_preview,
    }
