from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.models import SignalEvent

from core.signal_payload_v1 import EngineAnnotationsV1, EngineLevelV1, EngineZoneV1


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except Exception:
        return None
    return f if f == f else None


def _extract_entry_zone(evidence: Optional[Dict[str, Any]]) -> Optional[EngineZoneV1]:
    if not isinstance(evidence, dict):
        return None
    entry_zone = evidence.get("entry_zone")
    if not isinstance(entry_zone, dict):
        return None

    p_from = _num(entry_zone.get("price_from") or entry_zone.get("from") or entry_zone.get("low"))
    p_to = _num(entry_zone.get("price_to") or entry_zone.get("to") or entry_zone.get("high"))
    if p_from is None or p_to is None:
        return None

    lo = min(p_from, p_to)
    hi = max(p_from, p_to)
    if lo == hi:
        return None

    return EngineZoneV1(priceFrom=lo, priceTo=hi, label="Entry zone")


def build_engine_annotations_v1_from_signal(signal: SignalEvent) -> EngineAnnotationsV1:
    # Defensive: never crash even if `signal` is malformed.
    direction = str(getattr(signal, "direction", "") or "").upper().strip()

    entry = _num(getattr(signal, "entry", None))
    sl = _num(getattr(signal, "sl", None))
    tp = _num(getattr(signal, "tp", None))
    rr = _num(getattr(signal, "rr", None))

    levels = []
    if entry is not None:
        levels.append(EngineLevelV1(price=entry, label=f"ENTRY {direction}".strip()))
    if sl is not None:
        levels.append(EngineLevelV1(price=sl, label="SL"))
    if tp is not None:
        tp_label = "TP" if rr is None else f"TP (RR {rr:.2f})"
        levels.append(EngineLevelV1(price=tp, label=tp_label))

    evidence = getattr(signal, "evidence", None)
    entry_zone = _extract_entry_zone(evidence if isinstance(evidence, dict) else None)
    zones = [entry_zone] if entry_zone is not None else []

    # v1 contract: keep fiboZones empty unless explicitly provided by evidence in a future version.
    return EngineAnnotationsV1(levels=list(levels), zones=list(zones), fiboZones=[])


def build_public_drawings_from_setup(
    entry: Any,
    sl: Any,
    tp: Any,
    entry_zone: Optional[Dict[str, Any]] = None,
) -> List["DrawingObjectPublicV1"]:
    """Build minimal, NA-safe public drawings from a setup.

    Creates (when present):
    - ENTRY/SL/TP lines
    - label objects for each line
    - optional entry-zone box (if provided)
    - risk box between entry and sl
    - target box between entry and tp

    Deterministic ordering and IDs.
    """

    # Local import to avoid forcing UI schema dependency at module import time.
    from core.signal_payload_public_v1 import DrawingObjectPublicV1

    entry_f = _num(entry)
    sl_f = _num(sl)
    tp_f = _num(tp)

    out: List[DrawingObjectPublicV1] = []

    def _add_line(name: str, price: Optional[float], label: str) -> None:
        if price is None:
            return
        out.append(
            DrawingObjectPublicV1(
                object_id=f"pubv1:line:{name}",
                kind="line",
                label=label,
                price=price,
            )
        )
        out.append(
            DrawingObjectPublicV1(
                object_id=f"pubv1:label:{name}",
                kind="label",
                label=label,
                price=price,
            )
        )

    _add_line("entry", entry_f, "ENTRY")
    _add_line("sl", sl_f, "SL")
    _add_line("tp", tp_f, "TP")

    def _add_box(name: str, a: Optional[float], b: Optional[float], label: str) -> None:
        if a is None or b is None:
            return
        lo, hi = (a, b) if a <= b else (b, a)
        if lo == hi:
            return
        out.append(
            DrawingObjectPublicV1(
                object_id=f"pubv1:box:{name}",
                kind="box",
                label=label,
                price_from=lo,
                price_to=hi,
            )
        )

    # Optional entry zone from evidence-like dict.
    ez = entry_zone if isinstance(entry_zone, dict) else None
    if ez is not None:
        ez_from = _num(ez.get("price_from") or ez.get("from") or ez.get("low"))
        ez_to = _num(ez.get("price_to") or ez.get("to") or ez.get("high"))
        _add_box("entry_zone", ez_from, ez_to, "Entry zone")

    _add_box("risk", entry_f, sl_f, "Risk")
    _add_box("target", entry_f, tp_f, "Target")

    return out
