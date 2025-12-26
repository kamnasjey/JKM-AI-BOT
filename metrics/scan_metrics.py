from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


Status = Literal["OK", "NONE"]


_METRICS_LOCK = threading.Lock()


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


def _safe_jsonable(obj: Any, *, depth: int = 0, max_depth: int = 4, max_list: int = 50) -> Any:
    if depth > max_depth:
        return "..."

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in list(obj.items())[: int(max_list)]:
            out[_safe_str(k)] = _safe_jsonable(v, depth=depth + 1, max_depth=max_depth, max_list=max_list)
        return out

    if isinstance(obj, (list, tuple)):
        return [
            _safe_jsonable(x, depth=depth + 1, max_depth=max_depth, max_list=max_list)
            for x in list(obj)[: int(max_list)]
        ]

    return _safe_str(obj)


@dataclass(frozen=True)
class MetricsEvent:
    ts: float
    scan_id: str
    symbol: str
    tf: str
    strategy_id: str
    status: Status
    reason: str
    score: Optional[float]
    score_raw: Optional[float]
    bonus: Optional[float]
    rr: Optional[float]
    regime: str
    candidates: Optional[Any]
    failover_used: Optional[bool]
    params_digest: str
    # Optional coverage fields (backward compatible):
    top_hits: Optional[Any] = None
    hit_count: Optional[int] = None

    # Optional shadow coverage fields (when SHADOW_ALL_DETECTORS=1):
    shadow_hits: Optional[Any] = None
    shadow_hit_count: Optional[int] = None
    shadow_detectors_total: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "ts": float(self.ts),
            "scan_id": _safe_str(self.scan_id),
            "symbol": _safe_str(self.symbol),
            "tf": _safe_str(self.tf),
            "strategy_id": _safe_str(self.strategy_id),
            "status": _safe_str(self.status),
            "reason": _safe_str(self.reason),
            "score": self.score,
            "score_raw": self.score_raw,
            "bonus": self.bonus,
            "rr": self.rr,
            "regime": _safe_str(self.regime),
            "candidates": _safe_jsonable(self.candidates),
            "failover_used": bool(self.failover_used) if self.failover_used is not None else None,
            "params_digest": _safe_str(self.params_digest),
        }
        if self.top_hits is not None:
            out["top_hits"] = _safe_jsonable(self.top_hits)
        if self.hit_count is not None:
            out["hit_count"] = int(self.hit_count)
        if self.shadow_hits is not None:
            out["shadow_hits"] = _safe_jsonable(self.shadow_hits)
        if self.shadow_hit_count is not None:
            out["shadow_hit_count"] = int(self.shadow_hit_count)
        if self.shadow_detectors_total is not None:
            out["shadow_detectors_total"] = int(self.shadow_detectors_total)
        return out


def _coerce_str_list(v: Any, *, max_items: int = 10) -> list[str]:
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for x in v[: int(max_items)]:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _top_hits_from_explain(explain: Dict[str, Any]) -> list[str]:
    ex = explain if isinstance(explain, dict) else {}

    details = ex.get("details") if isinstance(ex.get("details"), dict) else {}
    ev = ex.get("evidence") if isinstance(ex.get("evidence"), dict) else {}

    # OK: details.top_hits is the canonical list from engine.
    top = _coerce_str_list(details.get("top_hits"))
    if top:
        return top

    # NONE: best-side contribs from score_breakdown (if present)
    bd = ev.get("score_breakdown") if isinstance(ev.get("score_breakdown"), dict) else {}
    items = bd.get("top_hit_contribs")
    if not isinstance(items, list) or not items:
        return []
    out: list[str] = []
    for it in items[:10]:
        if not isinstance(it, dict):
            continue
        name = str(it.get("detector") or "").strip()
        if name:
            out.append(name)
    # Stable + de-duped (preserve order)
    seen = set()
    uniq: list[str] = []
    for n in out:
        if n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    return uniq


def build_event_from_explain(
    *,
    explain: Dict[str, Any],
    candidates: Any = None,
    failover_used: Optional[bool] = None,
) -> MetricsEvent:
    ex = explain if isinstance(explain, dict) else {}
    details = ex.get("details") if isinstance(ex.get("details"), dict) else {}

    status_s = _safe_str(ex.get("status")).upper()
    status: Status = "OK" if status_s == "OK" else "NONE"

    top_hits = _top_hits_from_explain(ex)

    shadow_hits = _coerce_str_list(details.get("shadow_hits"), max_items=50)
    shadow_hit_count = None
    try:
        if details.get("shadow_hit_count") not in (None, "NA"):
            shadow_hit_count = int(details.get("shadow_hit_count"))
    except Exception:
        shadow_hit_count = None
    if shadow_hits and shadow_hit_count is None:
        shadow_hit_count = int(len(shadow_hits))

    shadow_detectors_total = None
    try:
        if details.get("shadow_detectors_total") not in (None, "NA"):
            shadow_detectors_total = int(details.get("shadow_detectors_total"))
    except Exception:
        shadow_detectors_total = None

    return MetricsEvent(
        ts=float(time.time()),
        scan_id=_safe_str(ex.get("scan_id")),
        symbol=_safe_str(ex.get("symbol")),
        tf=_safe_str(ex.get("tf")),
        strategy_id=_safe_str(ex.get("strategy_id")),
        status=status,
        reason=_safe_str(ex.get("reason")),
        score=_safe_float(details.get("score")),
        score_raw=_safe_float(details.get("score_raw")),
        bonus=_safe_float(details.get("bonus")),
        rr=_safe_float(details.get("rr")),
        regime=_safe_str(details.get("regime")),
        candidates=candidates,
        failover_used=failover_used,
        params_digest=_safe_str(details.get("params_digest")),
        top_hits=top_hits,
        hit_count=int(len(top_hits)),
        shadow_hits=shadow_hits if shadow_hits else None,
        shadow_hit_count=shadow_hit_count,
        shadow_detectors_total=shadow_detectors_total,
    )


def emit_event(event: MetricsEvent, *, path: str = "state/metrics_events.jsonl") -> None:
    """Append one JSONL line. Non-fatal by design."""
    try:
        from core.atomic_io import atomic_append_jsonl_via_replace

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        line = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with _METRICS_LOCK:
            atomic_append_jsonl_via_replace(Path(path), line)
    except Exception:
        return
