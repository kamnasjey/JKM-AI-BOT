from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from core.compat_aliases import normalize_detector_name, normalize_reason_code
from core.feature_flags import FeatureFlags
from engine.utils.logging_utils import log_kv_warning
from metrics.plugin_events import emit_plugin_event_now

from .base import BaseDetector, DetectorResult


def _short_err(e: BaseException, *, limit: int = 200) -> str:
    msg = f"{type(e).__name__}:{e}"
    s = str(msg).replace("\n", " ").replace("\r", " ")
    if len(s) > limit:
        return s[: limit - 3] + "..."
    return s


def _ensure_result_contract(r: Any, *, detector_name: str) -> DetectorResult:
    if isinstance(r, DetectorResult):
        # Normalize name + reason codes.
        r.detector_name = normalize_detector_name(r.detector_name or detector_name)
        r.reason_codes = [normalize_reason_code(x) for x in list(getattr(r, "reason_codes", []) or []) if str(x or "").strip()]
        # Force hit to reflect match.
        r.hit = bool(getattr(r, "match", False))
        return r

    # Best-effort adaptation for duck-typed results (SimpleNamespace / pydantic / dict-like).
    try:
        match = bool(getattr(r, "match"))
        det = getattr(r, "detector_name", None) or detector_name
        direction = getattr(r, "direction", None)
        confidence = getattr(r, "confidence", 0.5)

        reasons = getattr(r, "reasons", None)
        if not isinstance(reasons, list):
            reasons = []
        reasons_s = [str(x) for x in reasons if str(x or "").strip()]

        evd = getattr(r, "evidence_dict", None)
        if not isinstance(evd, dict):
            evd = {}

        tags = getattr(r, "tags", None)
        if not isinstance(tags, list):
            tags = []
        tags_s = [str(x) for x in tags if str(x or "").strip()]

        rc = getattr(r, "reason_codes", None)
        if not isinstance(rc, list):
            rc = []
        rc_s = [normalize_reason_code(x) for x in rc if str(x or "").strip()]

        out = DetectorResult(
            detector_name=normalize_detector_name(det),
            match=bool(match),
            direction=(direction if direction in ("BUY", "SELL") else None),
            confidence=float(confidence) if confidence is not None else 0.5,
            reasons=reasons_s,
            evidence_dict=dict(evd),
            tags=tags_s,
            score_contrib=getattr(r, "score_contrib", None),
            entry=getattr(r, "entry", None),
            sl=getattr(r, "sl", None),
            tp=getattr(r, "tp", None),
            rr=getattr(r, "rr", None),
            reason_codes=rc_s,
        )
        return out
    except Exception:
        pass

    # Best-effort adaptation for detectors returning unexpected types.
    return DetectorResult(
        detector_name=normalize_detector_name(detector_name),
        match=False,
        reasons=["DETECTOR_BAD_RESULT"],
        reason_codes=["DETECTOR_BAD_RESULT"],
        evidence_dict={"returned_type": str(type(r).__name__)},
    )


def safe_detect(
    detector: BaseDetector,
    *,
    candles: Any,
    primitives: Any,
    context: Optional[Dict[str, Any]] = None,
    logger: Any = None,
    scan_id: str = "NA",
    flags: Optional[FeatureFlags] = None,
) -> Tuple[DetectorResult, float]:
    """Run a detector safely.

    - Never raises.
    - On exception: records DETECTOR_RUNTIME_ERROR and returns hit=False.
    - Returns (result, elapsed_ms).
    """
    t0 = time.perf_counter()
    det_name = normalize_detector_name(getattr(detector, "name", None) or detector.get_name())
    try:
        # Use positional arg for context to support older/fake detectors.
        r = detector.detect(candles, primitives, context)
        out = _ensure_result_contract(r, detector_name=det_name)
        return out, (time.perf_counter() - t0) * 1000.0
    except Exception as e:
        msg = _short_err(e)

        emit_plugin_event_now(
            event="DETECTOR_RUNTIME_ERROR",
            scan_id=str(scan_id or "NA"),
            detector=str(det_name),
            message=msg,
            extra={"context": context or {}},
            flags=(flags.as_dict() if flags is not None else None),
        )
        if logger is not None:
            try:
                log_kv_warning(logger, "DETECTOR_RUNTIME_ERROR", scan_id=scan_id, detector=det_name, err=msg)
            except Exception:
                pass

        out = DetectorResult(
            detector_name=det_name,
            match=False,
            reasons=["DETECTOR_RUNTIME_ERROR"],
            reason_codes=["DETECTOR_RUNTIME_ERROR"],
            evidence_dict={"error": msg},
        )
        return out, (time.perf_counter() - t0) * 1000.0
