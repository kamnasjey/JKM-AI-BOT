from __future__ import annotations

from typing import Any, Dict, Optional


# Central alias mapping for backward compatibility.

# Detector reason code aliases (stable outputs on the right).
REASON_CODE_ALIASES: Dict[str, str] = {
    "DETECTOR_ERROR": "DETECTOR_RUNTIME_ERROR",
    "DETECTOR_RUNTIME_ERROR": "DETECTOR_RUNTIME_ERROR",
    "REGISTRY_LOAD_ISSUE": "REGISTRY_LOAD_ISSUE",
    "LOAD_ERROR": "REGISTRY_LOAD_ISSUE",
}


# Detector name aliases (legacy -> canonical).
DETECTOR_NAME_ALIASES: Dict[str, str] = {
    # Keep empty by default; add entries when renaming detectors.
    # "trend_fibo_v0": "trend_fibo",
}


# Schema field aliases (legacy -> canonical).
SCHEMA_FIELD_ALIASES: Dict[str, str] = {
    # DetectorResult
    "match": "hit",
    # Signals payload aliases handled elsewhere.
}


def normalize_reason_code(code: Any) -> str:
    s = str(code or "").strip()
    if not s:
        return "NA"
    return REASON_CODE_ALIASES.get(s, s)


def normalize_detector_name(name: Any) -> str:
    s = str(name or "").strip()
    if not s:
        return "NA"
    return DETECTOR_NAME_ALIASES.get(s, s)


def apply_schema_field_aliases(payload: Dict[str, Any], *, mapping: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Best-effort alias mapping. Never raises."""
    if not isinstance(payload, dict):
        return {}
    mp = mapping if isinstance(mapping, dict) else SCHEMA_FIELD_ALIASES
    out: Dict[str, Any] = dict(payload)
    try:
        for old, new in mp.items():
            if old in out and new not in out:
                out[new] = out.get(old)
    except Exception:
        return dict(payload)
    return out
