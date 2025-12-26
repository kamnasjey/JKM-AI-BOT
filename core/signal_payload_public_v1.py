from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, computed_field

from core.signal_payload_v1 import EngineAnnotationsV1, SignalPayloadV1


class DrawingObjectPublicV1(BaseModel):
    """Minimal chart drawing primitives for UI (public v1)."""

    object_id: str
    kind: Literal["line", "box", "label"]

    # Compatibility alias: some clients expect `type`.
    @computed_field(return_type=str)
    @property
    def type(self) -> str:
        return str(self.kind)

    label: Optional[str] = None

    # line
    price: Optional[float] = None

    # box
    price_from: Optional[float] = None
    price_to: Optional[float] = None


class SignalPayloadPublicV1(BaseModel):
    schema_name: Literal["SignalPayloadPublicV1"] = "SignalPayloadPublicV1"
    schema_version: int = 1

    signal_id: str
    created_at: int

    user_id: str
    symbol: str
    tf: str

    status: Literal["OK", "NONE"]
    direction: Literal["BUY", "SELL", "NA"]

    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    rr: Optional[float] = None

    explain: Dict[str, Any] = Field(default_factory=dict)

    # Must always exist (stable keys).
    evidence: Dict[str, Any] = Field(default_factory=dict)

    chart_drawings: List[DrawingObjectPublicV1] = Field(default_factory=list)

    # Backward/forward compatibility: expose canonical field names expected by UI.
    @computed_field(return_type=int)
    @property
    def ts_utc(self) -> int:
        return int(self.created_at)

    @computed_field(return_type=str)
    @property
    def timeframe(self) -> str:
        return str(self.tf)


def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except Exception:
        return None
    return f if f == f else None


def _safe_direction(direction: Any) -> Literal["BUY", "SELL", "NA"]:
    d = str(direction or "").upper().strip()
    if d == "BUY":
        return "BUY"
    if d == "SELL":
        return "SELL"
    return "NA"


def _stable_float_token(v: Optional[float]) -> str:
    if v is None:
        return "na"
    return format(v, ".10g")


def _stable_public_id(kind: str, name: str) -> str:
    return f"pubv1:{kind}:{name}".lower()


def _build_public_drawings_from_v1(payload: SignalPayloadV1) -> List[DrawingObjectPublicV1]:
    out: List[DrawingObjectPublicV1] = []

    # Prefer explicit drawings (already deterministic).
    if isinstance(payload.drawings, list) and payload.drawings:
        for d in payload.drawings:
            if getattr(d, "kind", None) == "level":
                price = _safe_float(getattr(d, "price", None))
                if price is None:
                    continue
                out.append(
                    DrawingObjectPublicV1(
                        object_id=str(getattr(d, "object_id", "") or "").strip() or _stable_public_id(
                            "line", _stable_float_token(price)
                        ),
                        kind="line",
                        label=getattr(d, "label", None),
                        price=price,
                    )
                )
            elif getattr(d, "kind", None) == "zone":
                p_from = _safe_float(getattr(d, "price_from", None))
                p_to = _safe_float(getattr(d, "price_to", None))
                if p_from is None or p_to is None:
                    continue
                lo, hi = (p_from, p_to) if p_from <= p_to else (p_to, p_from)
                if lo == hi:
                    continue
                out.append(
                    DrawingObjectPublicV1(
                        object_id=str(getattr(d, "object_id", "") or "").strip()
                        or _stable_public_id("box", f"{_stable_float_token(lo)}-{_stable_float_token(hi)}"),
                        kind="box",
                        label=getattr(d, "label", None),
                        price_from=lo,
                        price_to=hi,
                    )
                )

        return out

    # Best-effort: derive from engine annotations.
    annotations: EngineAnnotationsV1 = payload.engine_annotations or EngineAnnotationsV1()

    for lvl in list(getattr(annotations, "levels", []) or []):
        price = _safe_float(getattr(lvl, "price", None))
        if price is None:
            continue
        label = getattr(lvl, "label", None)
        name = str(label).strip().lower() if label else _stable_float_token(price)
        out.append(
            DrawingObjectPublicV1(
                object_id=_stable_public_id("line", name),
                kind="line",
                label=label,
                price=price,
            )
        )

    def _zones_to_boxes(zones: Any, prefix: str) -> None:
        for z in list(zones or []):
            p_from = _safe_float(getattr(z, "priceFrom", None))
            p_to = _safe_float(getattr(z, "priceTo", None))
            if p_from is None or p_to is None:
                continue
            lo, hi = (p_from, p_to) if p_from <= p_to else (p_to, p_from)
            if lo == hi:
                continue
            label = getattr(z, "label", None)
            name = (
                str(label).strip().lower()
                if label
                else f"{prefix}:{_stable_float_token(lo)}-{_stable_float_token(hi)}"
            )
            out.append(
                DrawingObjectPublicV1(
                    object_id=_stable_public_id("box", name),
                    kind="box",
                    label=label,
                    price_from=lo,
                    price_to=hi,
                )
            )

    _zones_to_boxes(getattr(annotations, "zones", None), "zone")
    _zones_to_boxes(getattr(annotations, "fiboZones", None), "fibo")

    return out


def _merge_drawings_dedup(
    base: List[DrawingObjectPublicV1],
    extra: List[DrawingObjectPublicV1],
) -> List[DrawingObjectPublicV1]:
    seen = set()
    out: List[DrawingObjectPublicV1] = []

    for d in base:
        oid = str(getattr(d, "object_id", "") or "").strip()
        if not oid or oid in seen:
            continue
        seen.add(oid)
        out.append(d)

    # Deterministic add: sort extras by object_id
    for d in sorted(extra, key=lambda x: str(getattr(x, "object_id", "") or "")):
        oid = str(getattr(d, "object_id", "") or "").strip()
        if not oid or oid in seen:
            continue
        seen.add(oid)
        out.append(d)

    return out


def to_public_v1(payload: SignalPayloadV1) -> SignalPayloadPublicV1:
    entry = _safe_float(payload.entry)
    sl = _safe_float(payload.sl)
    tp = _safe_float(payload.tp)
    rr = _safe_float(payload.rr)

    explain: Dict[str, Any] = payload.explain if isinstance(payload.explain, dict) else {}
    original_evidence = explain.get("evidence") if isinstance(explain.get("evidence"), dict) else {}

    stable = {
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "entry_zone": None,
    }

    extras: Dict[str, Any] = {}
    if isinstance(original_evidence, dict):
        for k in sorted(original_evidence.keys()):
            if k in stable:
                continue
            extras[k] = original_evidence.get(k)

    evidence: Dict[str, Any] = dict(stable)
    evidence.update(extras)

    if isinstance(original_evidence, dict) and original_evidence.get("entry_zone") is not None:
        evidence["entry_zone"] = original_evidence.get("entry_zone")

    # Deterministic, NA-safe drawings for UI.
    # Build minimal primitives from setup (ENTRY/SL/TP + labels + risk/target + optional entry zone),
    # then merge any legacy-derived drawings best-effort.
    from core.chart_annotation_builder import build_public_drawings_from_setup

    base_drawings = build_public_drawings_from_setup(
        entry=entry,
        sl=sl,
        tp=tp,
        entry_zone=(evidence.get("entry_zone") if isinstance(evidence.get("entry_zone"), dict) else None),
    )
    legacy_drawings = _build_public_drawings_from_v1(payload)
    drawings = _merge_drawings_dedup(base_drawings, legacy_drawings)

    return SignalPayloadPublicV1(
        signal_id=str(payload.signal_id),
        created_at=int(payload.created_at),
        user_id=str(payload.user_id),
        symbol=str(payload.symbol),
        tf=str(payload.tf),
        status="OK",
        direction=_safe_direction(payload.direction),
        entry=entry,
        sl=sl,
        tp=tp,
        rr=rr,
        explain=explain,
        evidence=evidence,
        chart_drawings=drawings,
    )


def to_public_v1_from_legacy_dict(legacy: Dict[str, Any]) -> SignalPayloadPublicV1:
    """Best-effort legacy dict -> public payload.

    Must never raise; fills missing fields with deterministic defaults.
    """

    if not isinstance(legacy, dict):
        legacy = {}

    created_at = legacy.get("created_at")
    if created_at is None:
        created_at = legacy.get("ts")
    try:
        created_at_i = int(created_at) if created_at is not None else 0
    except Exception:
        created_at_i = 0

    signal_id = str(legacy.get("signal_id") or legacy.get("id") or "NA")
    user_id = str(legacy.get("user_id") or "NA")
    symbol = str(legacy.get("symbol") or "NA")
    tf = str(legacy.get("tf") or legacy.get("timeframe") or "NA")

    # status / has_setup
    status_raw = str(legacy.get("status") or "").upper().strip()
    if status_raw in ("OK", "NONE"):
        status = status_raw  # type: ignore[assignment]
    else:
        try:
            has_setup = bool(legacy.get("has_setup"))
        except Exception:
            has_setup = False
        status = "OK" if has_setup else "NONE"

    direction = _safe_direction(legacy.get("direction"))
    entry = _safe_float(legacy.get("entry"))
    sl = _safe_float(legacy.get("sl"))
    tp = _safe_float(legacy.get("tp"))
    rr = _safe_float(legacy.get("rr"))

    explain = legacy.get("explain") if isinstance(legacy.get("explain"), dict) else {}

    # Evidence must always exist with stable keys.
    original_evidence = explain.get("evidence") if isinstance(explain.get("evidence"), dict) else {}
    stable: Dict[str, Any] = {
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "entry_zone": None,
    }
    extras: Dict[str, Any] = {}
    if isinstance(original_evidence, dict):
        for k in sorted(original_evidence.keys()):
            if k in stable:
                continue
            extras[k] = original_evidence.get(k)
    evidence: Dict[str, Any] = dict(stable)
    evidence.update(extras)
    if isinstance(original_evidence, dict) and original_evidence.get("entry_zone") is not None:
        evidence["entry_zone"] = original_evidence.get("entry_zone")
    elif isinstance(legacy.get("evidence"), dict) and legacy.get("evidence").get("entry_zone") is not None:  # type: ignore[union-attr]
        evidence["entry_zone"] = legacy.get("evidence").get("entry_zone")  # type: ignore[union-attr]

    from core.chart_annotation_builder import build_public_drawings_from_setup

    drawings = build_public_drawings_from_setup(entry, sl, tp, entry_zone=evidence.get("entry_zone"))

    return SignalPayloadPublicV1(
        signal_id=signal_id,
        created_at=created_at_i,
        user_id=user_id,
        symbol=symbol,
        tf=tf,
        status=status,  # type: ignore[arg-type]
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        rr=rr,
        explain=explain,
        evidence=evidence,
        chart_drawings=list(drawings),
    )
