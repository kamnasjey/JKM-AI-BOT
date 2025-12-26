from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


@dataclass(frozen=True)
class DeadDetectorDiagnosis:
    detector: str
    likely_causes: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detector": str(self.detector),
            "likely_causes": list(self.likely_causes),
            "suggestions": list(self.suggestions),
        }


def _as_str_set(values: Any) -> Set[str]:
    if values is None:
        return set()
    if isinstance(values, set):
        return {str(x).strip().upper() for x in values if str(x or "").strip()}
    if isinstance(values, (list, tuple)):
        return {str(x).strip().upper() for x in values if str(x or "").strip()}
    s = str(values).strip().upper()
    return {s} if s else set()


def _strategy_fields(
    strategy: Any,
) -> Tuple[str, bool, List[str], List[str], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Best-effort extract fields from StrategySpec or dict."""
    sid = "NA"
    enabled = True
    allowed_regimes: List[str] = []
    detectors: List[str] = []
    detector_params: Dict[str, Dict[str, Any]] = {}
    family_params: Dict[str, Dict[str, Any]] = {}

    if isinstance(strategy, dict):
        sid = str(strategy.get("strategy_id") or "NA")
        enabled = bool(strategy.get("enabled", True))
        ar = strategy.get("allowed_regimes")
        if isinstance(ar, list):
            allowed_regimes = [str(x).strip().upper() for x in ar if str(x or "").strip()]
        dets = strategy.get("detectors")
        if isinstance(dets, list):
            detectors = [str(x).strip() for x in dets if str(x or "").strip()]
        dp = strategy.get("detector_params")
        if isinstance(dp, dict):
            detector_params = {str(k): (dict(v) if isinstance(v, dict) else {}) for k, v in dp.items()}
        fp = strategy.get("family_params")
        if isinstance(fp, dict):
            family_params = {str(k): (dict(v) if isinstance(v, dict) else {}) for k, v in fp.items()}
        return sid, enabled, allowed_regimes, detectors, detector_params, family_params

    # StrategySpec dataclass
    sid = str(getattr(strategy, "strategy_id", "NA") or "NA")
    enabled = bool(getattr(strategy, "enabled", True))
    ar2 = getattr(strategy, "allowed_regimes", None)
    if isinstance(ar2, list):
        allowed_regimes = [str(x).strip().upper() for x in ar2 if str(x or "").strip()]
    dets2 = getattr(strategy, "detectors", None)
    if isinstance(dets2, list):
        detectors = [str(x).strip() for x in dets2 if str(x or "").strip()]
    dp2 = getattr(strategy, "detector_params", None)
    if isinstance(dp2, dict):
        detector_params = {str(k): (dict(v) if isinstance(v, dict) else {}) for k, v in dp2.items()}
    fp2 = getattr(strategy, "family_params", None)
    if isinstance(fp2, dict):
        family_params = {str(k): (dict(v) if isinstance(v, dict) else {}) for k, v in fp2.items()}
    return sid, enabled, allowed_regimes, detectors, detector_params, family_params


def _safe_num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        try:
            return int(v)
        except Exception:
            return None
    try:
        return int(str(v).strip())
    except Exception:
        return None


def _safe_bool(v: Any) -> Optional[bool]:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return None


def _schema_safe_range(schema: Mapping[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Return (safe_low, safe_high) range for suggestion text."""
    min_v = _safe_num(schema.get("min"))
    max_v = _safe_num(schema.get("max"))
    strict_low = _safe_num(schema.get("strict_low"))
    strict_high = _safe_num(schema.get("strict_high"))

    safe_low = strict_low if strict_low is not None else min_v
    safe_high = strict_high if strict_high is not None else max_v
    return safe_low, safe_high


def _format_range(low: Optional[float], high: Optional[float]) -> str:
    if low is None and high is None:
        return ""
    if low is None:
        return f"<= {high}"
    if high is None:
        return f">= {low}"
    return f"{low}..{high}"


def _validate_params_against_schema(
    *,
    effective_params: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """Return (issues, cause_codes, suggestions).

    issues: list of dicts describing violations.
    cause_codes includes PARAMS_INVALID and/or PARAMS_TOO_STRICT.
    suggestions are human-readable and include exact key/value + safe ranges.
    """
    issues: List[Dict[str, Any]] = []
    causes: List[str] = []
    suggestions: List[str] = []

    if not isinstance(schema, Mapping) or not schema:
        return issues, causes, suggestions

    for key, rule in schema.items():
        if not str(key or "").strip():
            continue
        if not isinstance(rule, Mapping):
            continue
        if key not in effective_params:
            continue

        raw_val = effective_params.get(key)
        expected = str(rule.get("type") or "").strip().lower()

        typed_val: Any = raw_val
        typed_ok = True
        if expected == "int":
            typed_val = _safe_int(raw_val)
            typed_ok = typed_val is not None
        elif expected == "float":
            typed_val = _safe_num(raw_val)
            typed_ok = typed_val is not None
        elif expected == "bool":
            typed_val = _safe_bool(raw_val)
            typed_ok = typed_val is not None
        elif expected.startswith("list"):
            typed_ok = isinstance(raw_val, list)
        elif expected == "str":
            typed_ok = isinstance(raw_val, str)

        min_v = _safe_num(rule.get("min"))
        max_v = _safe_num(rule.get("max"))
        strict_low = _safe_num(rule.get("strict_low"))
        strict_high = _safe_num(rule.get("strict_high"))
        default_v = rule.get("default")

        if not typed_ok:
            if "PARAMS_INVALID" not in causes:
                causes.append("PARAMS_INVALID")
            issues.append(
                {
                    "code": "PARAMS_INVALID",
                    "key": str(key),
                    "value": raw_val,
                    "expected_type": expected or "any",
                    "min": min_v,
                    "max": max_v,
                    "default": default_v,
                }
            )
            safe_low, safe_high = _schema_safe_range(rule)
            rng = _format_range(safe_low, safe_high) or _format_range(min_v, max_v)
            hint = f"{key}={raw_val!r} invalid (expected {expected or 'any'})"
            if rng:
                hint += f"; try {rng}"
            if default_v is not None:
                hint += f" (default {default_v})"
            suggestions.append(hint)
            continue

        # Numeric range checks
        if expected in ("int", "float"):
            vnum = float(typed_val)
            out_of_range = False
            if min_v is not None and vnum < min_v:
                out_of_range = True
            if max_v is not None and vnum > max_v:
                out_of_range = True

            if out_of_range:
                if "PARAMS_INVALID" not in causes:
                    causes.append("PARAMS_INVALID")
                issues.append(
                    {
                        "code": "PARAMS_INVALID",
                        "key": str(key),
                        "value": typed_val,
                        "expected_type": expected,
                        "min": min_v,
                        "max": max_v,
                        "default": default_v,
                    }
                )
                rng = _format_range(min_v, max_v)
                hint = f"{key}={typed_val} out of range"
                if rng:
                    hint += f"; use {rng}"
                if default_v is not None:
                    hint += f" (default {default_v})"
                suggestions.append(hint)
                continue

            # Strictness checks (schema-driven)
            too_strict = False
            if strict_low is not None and vnum < strict_low:
                too_strict = True
                rec = f">= {strict_low}"
            elif strict_high is not None and vnum > strict_high:
                too_strict = True
                rec = f"<= {strict_high}"
            else:
                rec = ""

            if too_strict:
                if "PARAMS_TOO_STRICT" not in causes:
                    causes.append("PARAMS_TOO_STRICT")
                safe_low, safe_high = _schema_safe_range(rule)
                safe_rng = _format_range(safe_low, safe_high)
                issues.append(
                    {
                        "code": "PARAMS_TOO_STRICT",
                        "key": str(key),
                        "value": typed_val,
                        "recommended": rec,
                        "safe_range": safe_rng,
                        "default": default_v,
                    }
                )
                hint = f"{key}={typed_val} too strict; set {rec}"
                if safe_rng:
                    hint += f" (safe {safe_rng})"
                if default_v is not None:
                    hint += f" (default {default_v})"
                suggestions.append(hint)

    return issues, causes, suggestions


def diagnose_dead_detectors(
    dead_list: Sequence[str],
    strategies_specs: Sequence[Any],
    registry_meta: Mapping[str, Mapping[str, Any]],
    window_stats: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Diagnose dead detectors with deterministic rule-based causes.

    Returns mapping:
      detector_name -> {"detector": ..., "likely_causes": [...], "suggestions": [...]}

        Cause codes:
      - NOT_IN_ANY_STRATEGY
      - REGIME_MISMATCH
            - PARAMS_INVALID
            - PARAMS_TOO_STRICT
      - REGISTRY_LOAD_ISSUE
    """
    _ = window_stats  # reserved for future heuristics (keep deterministic)

    dead = [str(x or "").strip() for x in (dead_list or [])]
    dead = [x for x in dead if x]

    # Normalize enabled strategies.
    strategies_norm: List[
        Tuple[str, List[str], Set[str], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]
    ] = []
    for s in (strategies_specs or []):
        sid, enabled, allowed_regimes, detectors, detector_params, family_params = _strategy_fields(s)
        if not enabled:
            continue
        strategies_norm.append((sid, detectors, _as_str_set(allowed_regimes), detector_params, family_params))

    out: Dict[str, Dict[str, Any]] = {}

    for det in sorted(set(dead)):
        causes: List[str] = []
        suggestions: List[str] = []

        meta = registry_meta.get(det)
        if not isinstance(meta, Mapping):
            causes.append("REGISTRY_LOAD_ISSUE")
            suggestions.append("Verify detector is registered (ensure_registry_loaded) and name matches")
            out[det] = DeadDetectorDiagnosis(detector=det, likely_causes=causes, suggestions=suggestions).to_dict()
            continue

        supported_regimes = _as_str_set(meta.get("supported_regimes"))
        family = str(meta.get("family") or "").strip()
        param_schema = meta.get("param_schema") if isinstance(meta, Mapping) else None
        schema_map: Dict[str, Dict[str, Any]] = dict(param_schema) if isinstance(param_schema, dict) else {}

        # Find referencing strategies.
        ref_strats: List[Tuple[str, Set[str], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]] = []
        for sid, detectors, allowed_set, detector_params, family_params in strategies_norm:
            if det in set(detectors or []):
                ref_strats.append((sid, allowed_set, detector_params, family_params))

        if not ref_strats:
            causes.append("NOT_IN_ANY_STRATEGY")
            suggestions.append("Add to at least one strategy allow-list (strategy.detectors)")
            out[det] = DeadDetectorDiagnosis(detector=det, likely_causes=causes, suggestions=suggestions).to_dict()
            continue

        # Regime mismatch if ALL referencing strategies have empty overlap.
        any_overlap = False
        for _sid, allowed_set, _params, _family_params in ref_strats:
            if not allowed_set or not supported_regimes:
                # If either is empty, treat as no overlap.
                continue
            if allowed_set.intersection(supported_regimes):
                any_overlap = True
                break

        if not any_overlap:
            causes.append("REGIME_MISMATCH")
            if supported_regimes:
                suggestions.append(
                    "Include at least one supported regime in strategy.allowed_regimes: "
                    + ",".join(sorted(supported_regimes))
                )
            else:
                suggestions.append("Adjust detector.supported_regimes or strategy.allowed_regimes to overlap")
            out[det] = DeadDetectorDiagnosis(detector=det, likely_causes=causes, suggestions=suggestions).to_dict()
            continue

        # Params diagnosis (schema-based only; no schema => no PARAMS_* causes).
        param_issues_all: List[Dict[str, Any]] = []
        param_suggestions: List[str] = []
        if schema_map:
            for _sid, _allowed_set, detector_params, family_params in ref_strats:
                fam_params = (family_params or {}).get(family) if family else None
                fam_params = fam_params if isinstance(fam_params, dict) else {}
                det_params = detector_params.get(det) if isinstance(detector_params, dict) else None
                det_params = det_params if isinstance(det_params, dict) else {}

                effective: Dict[str, Any] = {}
                effective.update(dict(fam_params))
                effective.update(dict(det_params))

                issues, cause_codes, sug = _validate_params_against_schema(
                    effective_params=effective,
                    schema=schema_map,
                )
                param_issues_all.extend(list(issues))
                for c in cause_codes:
                    if c not in causes:
                        causes.append(c)
                param_suggestions.extend(list(sug))

        if param_suggestions:
            # Deterministic dedupe preserve order
            seen = set()
            uniq: List[str] = []
            for s in param_suggestions:
                if s in seen:
                    continue
                seen.add(s)
                uniq.append(s)
            suggestions.extend(uniq[:3])

        # Attach bounded param issue details for deeper debugging.
        if param_issues_all:
            # Deterministic: keep first 5 after sorting by key+code.
            param_issues_all.sort(key=lambda x: (str(x.get("code")), str(x.get("key"))))
            out_row = DeadDetectorDiagnosis(detector=det, likely_causes=causes, suggestions=suggestions).to_dict()
            out_row["param_issues"] = param_issues_all[:5]
            out[det] = out_row
            continue

        out[det] = DeadDetectorDiagnosis(detector=det, likely_causes=causes, suggestions=suggestions).to_dict()

    return out


def compact_dead_diagnosis(
    diagnosis_details: Mapping[str, Mapping[str, Any]],
    *,
    limit: int = 5,
) -> Dict[str, List[str]]:
    """Return compact mapping: {detector: [cause_code, ...]} (deterministic; sorted by detector)."""
    out: Dict[str, List[str]] = {}
    if not isinstance(diagnosis_details, Mapping):
        return out

    for det in sorted([str(k) for k in diagnosis_details.keys() if str(k or "").strip()]):
        if len(out) >= int(limit):
            break
        row = diagnosis_details.get(det)
        if not isinstance(row, Mapping):
            continue
        lc = row.get("likely_causes")
        if isinstance(lc, list):
            causes = [str(x).strip() for x in lc if str(x or "").strip()]
        else:
            causes = []
        out[str(det)] = causes

    return out
