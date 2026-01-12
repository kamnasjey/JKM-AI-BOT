from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class EngineLevelV1(BaseModel):
    price: float
    label: Optional[str] = None


class EngineZoneV1(BaseModel):
    priceFrom: float
    priceTo: float
    label: Optional[str] = None


class EngineAnnotationsV1(BaseModel):
    levels: List[EngineLevelV1] = Field(default_factory=list)
    zones: List[EngineZoneV1] = Field(default_factory=list)
    fiboZones: List[EngineZoneV1] = Field(default_factory=list)


class DrawingObjectV1(BaseModel):
    """Stable drawing schema (v1).

    This intentionally overlaps with the current frontend overlay primitives:
    - level => horizontal line
    - zone => price band box
    """

    object_id: str
    # v1 drawing primitives:
    # - level: horizontal line
    # - zone: price band box
    kind: Literal["level", "zone"]
    label: Optional[str] = None

    # level
    price: Optional[float] = None

    # zone
    price_from: Optional[float] = None
    price_to: Optional[float] = None


class SignalPayloadV1(BaseModel):
    schema_name: Literal["SignalPayloadV1"] = "SignalPayloadV1"
    schema_version: int = 1

    signal_id: str
    created_at: int = Field(default_factory=lambda: int(time.time()))

    # Legacy/compat field (older code/tests may pass ISO timestamp string)
    timestamp: Optional[str] = None

    user_id: str
    symbol: str
    tf: str

    direction: str
    # NA-safe: values may be None.
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    rr: Optional[float] = None

    score: Optional[float] = None
    strategy_id: str
    scan_id: str

    reasons: List[str] = Field(default_factory=list)

    explain: Dict[str, Any] = Field(default_factory=dict)

    engine_annotations: EngineAnnotationsV1 = Field(default_factory=EngineAnnotationsV1)
    drawings: List[DrawingObjectV1] = Field(default_factory=list)


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except Exception:
        return None
    if f != f:
        return None
    return f


def _stable_drawing_id(kind: str, name: str) -> str:
    return f"v1:{kind}:{name}".lower()


def build_drawings_v1(
    *,
    direction: str,
    entry: Any,
    sl: Any,
    tp: Any,
    rr: Any,
    evidence: Optional[Dict[str, Any]] = None,
) -> List[DrawingObjectV1]:
    """Build deterministic drawings for Signal Visualization v1.

    Rules:
    - ENTRY/SL/TP are horizontal lines (kind=level) with stable IDs.
    - Optional entry zone box (kind=zone) only when evidence has entry_zone bounds.
    - Skip any drawing when its values are NA/None.
    """

    d = str(direction or "").upper().strip() or "NA"
    entry_f = _safe_float(entry)
    sl_f = _safe_float(sl)
    tp_f = _safe_float(tp)
    rr_f = _safe_float(rr)

    out: List[DrawingObjectV1] = []

    if entry_f is not None:
        out.append(
            DrawingObjectV1(
                object_id=_stable_drawing_id("level", "entry"),
                kind="level",
                label=f"ENTRY {d}".strip(),
                price=entry_f,
            )
        )

    if sl_f is not None:
        out.append(
            DrawingObjectV1(
                object_id=_stable_drawing_id("level", "sl"),
                kind="level",
                label="SL",
                price=sl_f,
            )
        )

    if tp_f is not None:
        tp_label = "TP" if rr_f is None else f"TP (RR {rr_f:.2f})"
        out.append(
            DrawingObjectV1(
                object_id=_stable_drawing_id("level", "tp"),
                kind="level",
                label=tp_label,
                price=tp_f,
            )
        )

    ev = evidence or {}
    entry_zone = ev.get("entry_zone") if isinstance(ev, dict) else None
    if isinstance(entry_zone, dict):
        p_from = _safe_float(entry_zone.get("price_from") or entry_zone.get("from") or entry_zone.get("low"))
        p_to = _safe_float(entry_zone.get("price_to") or entry_zone.get("to") or entry_zone.get("high"))
        if p_from is not None and p_to is not None:
            lo = min(p_from, p_to)
            hi = max(p_from, p_to)
            if lo != hi:
                out.append(
                    DrawingObjectV1(
                        object_id=_stable_drawing_id("zone", "entry_zone"),
                        kind="zone",
                        label="Entry zone",
                        price_from=lo,
                        price_to=hi,
                    )
                )

    return out


def build_payload_v1(
    *,
    user_id: str,
    symbol: str,
    tf: str,
    direction: str,
    entry: Any = None,
    sl: Any = None,
    tp: Any = None,
    rr: Any = None,
    strategy_id: str,
    scan_id: str,
    reasons: Optional[List[str]] = None,
    explain: Optional[Dict[str, Any]] = None,
    score: Any = None,
    engine_annotations: Optional[EngineAnnotationsV1] = None,
) -> SignalPayloadV1:
    annotations = engine_annotations or EngineAnnotationsV1()

    ev = dict(explain or {})
    # Build deterministic drawings primarily from values/evidence.
    drawings: List[DrawingObjectV1] = build_drawings_v1(
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        rr=rr,
        evidence=(ev.get("evidence") if isinstance(ev.get("evidence"), dict) else None),
    )

    # Back-compat: if caller provided engine_annotations with shapes but
    # drawings list is empty, derive drawings from annotations (still deterministic ordering).
    if not drawings and annotations and (annotations.levels or annotations.zones or annotations.fiboZones):
        for lvl in annotations.levels:
            drawings.append(
                DrawingObjectV1(
                    object_id=_stable_drawing_id("level", str(lvl.label or "level")),
                    kind="level",
                    label=lvl.label,
                    price=lvl.price,
                )
            )
        for z in annotations.zones:
            drawings.append(
                DrawingObjectV1(
                    object_id=_stable_drawing_id("zone", str(z.label or "zone")),
                    kind="zone",
                    label=z.label,
                    price_from=z.priceFrom,
                    price_to=z.priceTo,
                )
            )
        for z in annotations.fiboZones:
            drawings.append(
                DrawingObjectV1(
                    object_id=_stable_drawing_id("zone", str(z.label or "fibo")),
                    kind="zone",
                    label=z.label,
                    price_from=z.priceFrom,
                    price_to=z.priceTo,
                )
            )

    return SignalPayloadV1(
        signal_id=uuid.uuid4().hex,
        created_at=int(time.time()),
        user_id=str(user_id),
        symbol=str(symbol).upper(),
        tf=str(tf),
        direction=str(direction).upper(),
        entry=_safe_float(entry),
        sl=_safe_float(sl),
        tp=_safe_float(tp),
        rr=_safe_float(rr),
        score=_safe_float(score),
        strategy_id=str(strategy_id),
        scan_id=str(scan_id),
        reasons=list(reasons or []),
        explain=dict(explain or {}),
        engine_annotations=annotations,
        drawings=drawings,
    )
