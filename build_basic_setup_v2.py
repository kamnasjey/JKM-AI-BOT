from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from engine_blocks import Setup, TrendInfo


RR_BELOW_MIN = "RR_BELOW_MIN"


@dataclass
class BuildSetupResult:
    ok: bool
    setup: Optional[Setup] = None
    fail_reason: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except Exception:
        return None
    return f if f == f else None


def _zone_width_abs(z: Any) -> float:
    lo = _safe_float(getattr(z, "lower", None))
    hi = _safe_float(getattr(z, "upper", None))
    if lo is None or hi is None:
        return 0.0
    return abs(float(hi) - float(lo))


def _zone_to_evidence(z: Any) -> Dict[str, Any]:
    if z is None:
        return {}
    return {
        "level": _safe_float(getattr(z, "level", None)),
        "lower": _safe_float(getattr(z, "lower", None)),
        "upper": _safe_float(getattr(z, "upper", None)),
        "strength": int(getattr(z, "strength", 0) or 0),
        "is_resistance": bool(getattr(z, "is_resistance", False)),
    }


def build_basic_setup_v2(
    *,
    pair: str,
    direction: str,
    entry_price: float,
    primitives: Any,
    min_rr: float,
    profile: Optional[Dict[str, Any]] = None,
) -> BuildSetupResult:
    """Indicator-free setup builder used by the v1 engine.

    Uses clustered S/R zones if available:
    - SELL: enter at resistance upper edge, SL = upper + 25% zone width
            TP at nearest support level below
    - BUY:  enter at support lower edge, SL = lower - 25% zone width
            TP at nearest resistance level above

    Returns RR_BELOW_MIN with evidence when RR < min_rr.
    """

    pair = str(pair or "").upper().strip()
    dir_u = str(direction or "").upper().strip()
    profile = dict(profile or {})

    try:
        entry_raw = float(entry_price)
    except Exception:
        entry_raw = 0.0

    zones = []
    try:
        zones = list(getattr(primitives, "sr_zones_clustered", None) or [])
    except Exception:
        zones = []

    supports = [z for z in zones if not bool(getattr(z, "is_resistance", False))]
    resistances = [z for z in zones if bool(getattr(z, "is_resistance", False))]

    if dir_u not in {"BUY", "SELL"}:
        return BuildSetupResult(ok=False, fail_reason="BAD_DIRECTION", evidence={"direction": dir_u})

    def _pick_entry_zone() -> Any:
        if dir_u == "SELL":
            if not resistances:
                return None
            # Closest resistance (by upper edge) to current entry.
            return min(
                resistances,
                key=lambda z: abs(((_safe_float(getattr(z, "upper", None)) or 0.0) - entry_raw)),
            )
        if not supports:
            return None
        return min(
            supports,
            key=lambda z: abs(((_safe_float(getattr(z, "lower", None)) or 0.0) - entry_raw)),
        )

    entry_zone = _pick_entry_zone()
    if entry_zone is None:
        return BuildSetupResult(ok=False, fail_reason="NO_ENTRY_ZONE", evidence={"direction": dir_u})

    z_lo = _safe_float(getattr(entry_zone, "lower", None))
    z_hi = _safe_float(getattr(entry_zone, "upper", None))
    z_level = _safe_float(getattr(entry_zone, "level", None))

    width = _zone_width_abs(entry_zone)
    buffer_abs = float(width) * 0.25

    if dir_u == "SELL":
        entry = float(z_hi if z_hi is not None else (z_level if z_level is not None else entry_raw))
        sl = float(entry + buffer_abs)

        # Target: closest support below entry.
        candidates = []
        for z in supports:
            lvl = _safe_float(getattr(z, "level", None))
            if lvl is None:
                continue
            if float(lvl) < entry:
                candidates.append((abs(entry - float(lvl)), float(lvl), z))
        if not candidates:
            return BuildSetupResult(
                ok=False,
                fail_reason="NO_TARGET",
                evidence={"entry": entry, "direction": dir_u, "entry_zone": _zone_to_evidence(entry_zone)},
            )
        _dist, tp, target_zone = min(candidates, key=lambda x: x[0])
    else:
        entry = float(z_lo if z_lo is not None else (z_level if z_level is not None else entry_raw))
        sl = float(entry - buffer_abs)

        # Target: closest resistance above entry.
        candidates = []
        for z in resistances:
            lvl = _safe_float(getattr(z, "level", None))
            if lvl is None:
                continue
            if float(lvl) > entry:
                candidates.append((abs(float(lvl) - entry), float(lvl), z))
        if not candidates:
            return BuildSetupResult(
                ok=False,
                fail_reason="NO_TARGET",
                evidence={"entry": entry, "direction": dir_u, "entry_zone": _zone_to_evidence(entry_zone)},
            )
        _dist, tp, target_zone = min(candidates, key=lambda x: x[0])

    sl_dist = abs(entry - float(sl))
    tp_dist = abs(float(tp) - entry)
    rr = float(tp_dist / sl_dist) if sl_dist > 0 else 0.0

    evidence = {
        "rr": rr,
        "min_rr": float(min_rr),
        "sl_dist": float(sl_dist),
        "tp_dist": float(tp_dist),
        "entry": float(entry),
        "sl": float(sl),
        "tp": float(tp),
        "entry_zone": _zone_to_evidence(entry_zone),
        "target_zone": _zone_to_evidence(target_zone),
        "buffer_abs": float(buffer_abs),
    }

    if rr < float(min_rr):
        return BuildSetupResult(ok=False, fail_reason=RR_BELOW_MIN, evidence=evidence)

    trend_dir = "down" if dir_u == "SELL" else "up"
    setup = Setup(
        pair=pair,
        direction=dir_u,  # type: ignore[arg-type]
        entry=float(entry),
        sl=float(sl),
        tp=float(tp),
        rr=float(rr),
        trend_info=TrendInfo(direction=trend_dir, ma=0.0, last_close=float(entry)),
        fibo_info=None,
    )

    return BuildSetupResult(ok=True, setup=setup, evidence=evidence)
