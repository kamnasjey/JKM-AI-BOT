from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from strategies.presets import apply_preset, get_preset
from strategies.strategy_spec import StrategySpec

from engines.detectors import detector_registry

from engine.utils.params_utils import sanitize_params

from strategies.detector_name_resolver import resolve_detector_names


_STRATEGY_ID_SAFE_RE = re.compile(r"[^a-z0-9_\-]+")


@dataclass(frozen=True)
class StrategyLoadResult:
    strategies: List[Dict[str, Any]]
    errors: List[str]

    @property
    def ok(self) -> bool:
        return bool(self.strategies)


@dataclass(frozen=True)
class StrategyPackLoadResult:
    schema_version: int
    include_presets: List[str]
    loaded_presets: List[str]
    missing_presets: List[str]

    strategies: List[StrategySpec]
    invalid_enabled: List[Dict[str, Any]]

    errors: List[str]
    warnings: List[str]

    # Per-strategy warnings for diagnostics (e.g., unknown detectors).
    strategy_warnings: Dict[str, List[str]]

    # Unknown detector names referenced by each strategy_id.
    unknown_detectors_by_strategy: Dict[str, List[str]]

    # Unknown detector suggestions (top matches) by strategy_id.
    unknown_detector_suggestions_by_strategy: Dict[str, Dict[str, List[str]]]

    # Strict-mode disabled strategies (in-memory only).
    disabled_unknown_detectors: Dict[str, List[str]]

    # High-confidence auto-fix patch suggestions for unknown detectors (dry-run).
    unknown_detector_autofix_patches: List[Dict[str, Any]]

    @property
    def ok(self) -> bool:
        return bool(self.strategies)


def _slugify_strategy_id(value: str) -> str:
    s = (value or "").strip().lower().replace(" ", "_")
    s = _STRATEGY_ID_SAFE_RE.sub("", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _coerce_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _env_flag(name: str, default: bool = False) -> bool:
    try:
        raw = os.getenv(str(name), "")
    except Exception:
        raw = ""
    s = str(raw or "").strip().lower()
    if not s:
        return bool(default)
    return s in ("1", "true", "yes", "y", "on")


def _safe_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _stable_patch_id(*, patch_type: str, date: str, strategy_id: str, replacements: Dict[str, str]) -> str:
    payload = {
        "patch_type": str(patch_type),
        "date": str(date),
        "strategy_id": str(strategy_id),
        "replacements": dict(replacements or {}),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        xs = str(x or "").strip()
        if not xs:
            continue
        if xs in seen:
            continue
        seen.add(xs)
        out.append(xs)
    return out


def _persist_patch_suggestions_items(out_path: str, items: List[Dict[str, Any]]) -> None:
    """Best-effort append/merge patch suggestions (atomic)."""
    try:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    except Exception:
        return

    if not items:
        return

    try:
        existing: Dict[str, Any] = {}
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as f:
                existing = json.load(f) or {}
        if not isinstance(existing, dict):
            existing = {}
        existing_items = existing.get("items") if isinstance(existing.get("items"), list) else []
        merged: Dict[str, Dict[str, Any]] = {}
        for it in existing_items:
            if isinstance(it, dict) and str(it.get("patch_id") or ""):
                merged[str(it.get("patch_id"))] = it
        for it in items:
            if isinstance(it, dict) and str(it.get("patch_id") or ""):
                merged[str(it.get("patch_id"))] = it
        payload = {"schema": int(existing.get("schema") or 1), "items": list(merged.values())}
        tmp = f"{out_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, out_path)
    except Exception:
        return


def summarize_unknown_detectors(
    pack: StrategyPackLoadResult,
    *,
    max_items: int = 10,
) -> Dict[str, Any]:
    """Return summary kv for logging STRATEGIES_LOADED.

    Keys:
      - unknown_detectors_count (unique detector names)
      - unknown_detectors_names (list, max_items)
      - unknown_detectors_strategies (list, max_items)
    """
    by_strategy = getattr(pack, "unknown_detectors_by_strategy", {}) or {}
    if not isinstance(by_strategy, dict):
        by_strategy = {}

    names_set = set()
    strategies_set = set()
    for sid, names in by_strategy.items():
        sid_s = str(sid or "").strip()
        if sid_s:
            strategies_set.add(sid_s)
        if isinstance(names, list):
            for n in names:
                ns = str(n or "").strip()
                if ns:
                    names_set.add(ns)

    names = sorted(list(names_set))
    strategies = sorted(list(strategies_set))
    return {
        "unknown_detectors_count": int(len(names)),
        "unknown_detectors_names": names[: int(max_items)],
        "unknown_detectors_strategies": strategies[: int(max_items)],
    }


def summarize_unknown_detector_suggestions(
    pack: StrategyPackLoadResult,
    *,
    max_strategies: int = 10,
    max_unknown_per_strategy: int = 5,
) -> Dict[str, Any]:
    """Return compact suggestions payload for admin-only logging."""
    raw = getattr(pack, "unknown_detector_suggestions_by_strategy", {}) or {}
    if not isinstance(raw, dict):
        raw = {}

    out: Dict[str, Any] = {}
    used = 0
    for sid in sorted(raw.keys()):
        if used >= int(max_strategies):
            break
        s_map = raw.get(sid)
        if not isinstance(s_map, dict) or not s_map:
            continue
        compact: Dict[str, Any] = {}
        u_used = 0
        for unk in sorted(s_map.keys()):
            if u_used >= int(max_unknown_per_strategy):
                break
            sugg = s_map.get(unk)
            if isinstance(sugg, list) and sugg:
                compact[str(unk)] = list(sugg)[:3]
                u_used += 1
        if compact:
            out[str(sid)] = compact
            used += 1

    return {"unknown_detector_suggestions": out}


def _load_detector_aliases(path: str) -> Dict[str, str]:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in obj.items():
        ks = str(k or "").strip()
        vs = str(v or "").strip()
        if ks and vs:
            out[ks] = vs
    return out


def _coerce_float(v: Any, *, default: float) -> float:
    if v is None:
        return float(default)
    try:
        return float(v)
    except Exception:
        return float(default)


def _coerce_int(v: Any, *, default: int) -> int:
    if v is None:
        return int(default)
    try:
        return int(v)
    except Exception:
        return int(default)


def _parse_json_maybe(value: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Parse a dict-like object.

    Accepts:
    - dict => returns as-is
    - str => json.loads

    Returns:
        (obj, err) where err is a short code string.
    """
    if isinstance(value, dict):
        return value, None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None, "EMPTY_JSON"
        # Convenience: allow specifying a preset id as a bare string.
        # Example: "trend_pullback_v1"
        preset = get_preset(s)
        if preset is not None:
            return preset, None
        try:
            obj = json.loads(s)
        except Exception:
            return None, "INVALID_JSON"
        if not isinstance(obj, dict):
            return None, "JSON_NOT_OBJECT"
        return obj, None
    if value is None:
        return None, "MISSING"
    return None, "UNSUPPORTED_TYPE"


def normalize_strategy_spec(raw: Dict[str, Any], *, idx: int) -> Dict[str, Any]:
    """Normalize a raw strategy config to StrategySpec v1.

    Notes:
    - Does not raise.
    - Adds defaults.
    - Converts detector allow-list list[str] into dict config.
    """
    s: Dict[str, Any] = dict(raw or {})

    # Preset overlay support.
    # Example: {"preset_id": "trend_pullback_v1", "min_score": 1.5}
    preset_id = str(s.get("preset_id") or s.get("preset") or "").strip()
    if preset_id:
        merged = apply_preset(preset_id, s)
        if merged is not None:
            s = merged

    s["enabled"] = _coerce_bool(s.get("enabled"), True)

    # strategy_id
    sid = str(s.get("strategy_id") or "").strip()
    if not sid:
        base = _slugify_strategy_id(str(s.get("name") or ""))
        if not base:
            base = f"strategy_{idx + 1}"
        suffix_src = f"{base}:{idx}:{s.get('name') or ''}"
        suffix = hashlib.sha1(suffix_src.encode("utf-8")).hexdigest()[:6]
        sid = f"{base}_{suffix}"
    s["strategy_id"] = sid

    # Core numeric defaults
    if "min_rr" in s:
        s["min_rr"] = _coerce_float(s.get("min_rr"), default=0.0)
    if "min_score" in s:
        s["min_score"] = _coerce_float(s.get("min_score"), default=0.0)

    # Strategy-level governance (optional)
    if "cooldown_minutes" in s and s.get("cooldown_minutes") is not None:
        s["cooldown_minutes"] = _coerce_int(s.get("cooldown_minutes"), default=0)
    if "daily_limit" in s and s.get("daily_limit") is not None:
        s["daily_limit"] = _coerce_int(s.get("daily_limit"), default=0)

    # Soft-combine params
    if "epsilon" in s:
        s["epsilon"] = _coerce_float(s.get("epsilon"), default=0.15)
    if "family_bonus" in s:
        s["family_bonus"] = _coerce_float(s.get("family_bonus"), default=0.25)

    # weights / detector_weight_overrides
    if "weights" in s and not isinstance(s.get("weights"), dict):
        s["weights"] = {}
    if "detector_weight_overrides" in s and not isinstance(s.get("detector_weight_overrides"), dict):
        s["detector_weight_overrides"] = {}

    # detectors allow-list: normalize to list[str]
    dets = s.get("detectors")
    if isinstance(dets, dict):
        norm_list: List[str] = []
        for k, v in dets.items():
            name = str(k or "").strip()
            if not name:
                continue
            enabled = True
            if isinstance(v, dict) and v.get("enabled") is not None:
                enabled = _coerce_bool(v.get("enabled"), True)
            elif isinstance(v, bool):
                enabled = bool(v)
            if enabled:
                norm_list.append(name)
        s["detectors"] = norm_list
    elif isinstance(dets, list):
        norm_list = []
        for x in dets:
            xs = str(x or "").strip()
            if xs:
                norm_list.append(xs)
        s["detectors"] = norm_list

    # allowed_regimes normalization
    ar = s.get("allowed_regimes")
    if isinstance(ar, (list, tuple)):
        norm = []
        for x in ar:
            xs = str(x or "").strip().upper()
            if xs:
                norm.append(xs)
        s["allowed_regimes"] = norm

    return s


def validate_strategy_spec(spec: Dict[str, Any]) -> List[str]:
    """Return list of validation error codes (empty == valid)."""
    errors: List[str] = []

    sid = spec.get("strategy_id")
    if not isinstance(sid, str) or not sid.strip():
        errors.append("MISSING_STRATEGY_ID")

    if "enabled" in spec and not isinstance(spec.get("enabled"), bool):
        errors.append("BAD_ENABLED")

    for k in ("min_score", "min_rr", "epsilon", "family_bonus"):
        if k in spec and spec.get(k) is not None:
            try:
                float(spec.get(k))
            except Exception:
                errors.append(f"BAD_{k.upper()}")

    for k in ("cooldown_minutes", "daily_limit"):
        if k in spec and spec.get(k) is not None:
            try:
                int(spec.get(k))
            except Exception:
                errors.append(f"BAD_{k.upper()}")

    if "detectors" in spec and spec.get("detectors") is not None:
        dets = spec.get("detectors")
        if not isinstance(dets, list):
            errors.append("BAD_DETECTORS")
        else:
            for d in dets:
                if not isinstance(d, str) or not d.strip():
                    errors.append("BAD_DETECTORS")
                    break

    # preset_id is allowed as input but should not survive normalization
    if "preset_id" in spec or "preset" in spec:
        errors.append("UNNORMALIZED_PRESET")

    for k in ("weights", "detector_weight_overrides"):
        if k in spec and spec.get(k) is not None and not isinstance(spec.get(k), dict):
            errors.append(f"BAD_{k.upper()}")

    ar = spec.get("allowed_regimes")
    if ar is not None and not isinstance(ar, list):
        errors.append("BAD_ALLOWED_REGIMES")

    return errors


def load_strategies_from_profile(profile: Dict[str, Any]) -> StrategyLoadResult:
    """Load StrategySpec list from a user profile without raising.

    Backward compatible inputs:
    - profile['strategy'] (dict or JSON string)
    - profile['strategies'] (list[dict] or list[str JSON])
    - fallback: treat profile itself as a single strategy-like config

    Invalid configs produce errors and an empty strategies list.
    """
    errors: List[str] = []
    raw_items: List[Any] = []

    # Require explicit strategies by default.
    # Legacy fallback (treating the whole profile as a strategy) can be re-enabled
    # only by setting ALLOW_PROFILE_STRATEGY_FALLBACK=1.
    require_explicit = _env_flag("REQUIRE_USER_STRATEGY", default=True)
    if "REQUIRE_STRATEGIES" in os.environ:
        require_explicit = _env_flag("REQUIRE_STRATEGIES", default=require_explicit)
    if _env_flag("ALLOW_PROFILE_STRATEGY_FALLBACK", default=False):
        require_explicit = False

    if isinstance(profile.get("strategy"), (dict, str)):
        raw_items = [profile.get("strategy")]
    elif isinstance(profile.get("strategies"), list) and profile.get("strategies"):
        raw_items = list(profile.get("strategies") or [])
    else:
        raw_items = [] if require_explicit else [profile]

    out: List[Dict[str, Any]] = []
    # Resolve known detector names across both registries.
    # The codebase has both `detectors/` and `engines/detectors/` namespaces;
    # tests expect the engine registry names (e.g., range_box_edge).
    known_detectors = set()
    try:
        from detectors.registry import DETECTOR_REGISTRY

        known_detectors |= set(DETECTOR_REGISTRY.keys())
    except Exception:
        pass
    try:
        known_detectors |= set(detector_registry.list_detectors() or [])
    except Exception:
        pass
    for idx, raw in enumerate(raw_items):
        obj, err = _parse_json_maybe(raw)
        if err:
            errors.append(f"STRATEGY_{idx}:{err}")
            continue
        if not obj:
            errors.append(f"STRATEGY_{idx}:EMPTY")
            continue

        # If a preset_id was provided but unknown, obj will still be a dict with preset_id.
        # normalize_strategy_spec will try overlay; if it can't resolve it, we treat as invalid.
        if isinstance(obj, dict):
            pid = str(obj.get("preset_id") or obj.get("preset") or "").strip()
            if pid and get_preset(pid) is None:
                errors.append(f"STRATEGY_{idx}:UNKNOWN_PRESET")
                continue

        spec = normalize_strategy_spec(obj, idx=idx)
        v_errs = validate_strategy_spec(spec)
        if v_errs:
            errors.append(f"STRATEGY_{idx}:" + ",".join(v_errs))
            continue

        if not bool(spec.get("enabled", True)):
            continue

        # Drop unknown detectors (best-effort), but never erase a user-provided allow-list.
        # If filtering would result in an empty list, keep the original list and let the
        # downstream registry/runner ignore unknown names safely.
        dets = spec.get("detectors")
        if known_detectors and isinstance(dets, list) and dets:
            filtered = [d for d in dets if d in known_detectors]
            dropped = [d for d in dets if d not in known_detectors]
            if dropped:
                errors.append(f"STRATEGY_{idx}:UNKNOWN_DETECTORS")
            if filtered:
                spec["detectors"] = filtered

        out.append(spec)

    return StrategyLoadResult(strategies=out, errors=errors)


def _safe_read_json_file(path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, "FILE_NOT_FOUND"
    except Exception:
        return None, "INVALID_JSON"

    if not isinstance(data, dict):
        return None, "JSON_NOT_OBJECT"
    return data, None


def _coerce_schema_version(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return int(value)
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _coerce_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for x in value:
        xs = str(x or "").strip()
        if xs:
            out.append(xs)
    return out


def _load_preset_pack_strategy_dicts(
    preset_id: str,
    *,
    presets_dir: str,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Load a preset pack from config/presets.

    Expected file shape (v1):
        {"preset_id": "...", "schema_version": 1, "strategies": [ {...}, ... ]}

    Returns:
        (strategies, err_code)
    """
    pid = str(preset_id or "").strip()
    if not pid:
        return None, "EMPTY_PRESET_ID"

    # Preferred: JSON pack file.
    pack_path = str(Path(presets_dir) / f"{pid}.json")
    data, err = _safe_read_json_file(pack_path)
    if err is None and isinstance(data, dict):
        raw = data.get("strategies")
        if isinstance(raw, list):
            out: List[Dict[str, Any]] = [x for x in raw if isinstance(x, dict)]
            return out, None
        return None, "PRESET_STRATEGIES_BAD_SHAPE"

    # Back-compat fallback: in-code presets.
    fallback = get_preset(pid)
    if fallback is not None:
        return [fallback], None

    return None, "PRESET_NOT_FOUND"


def load_strategy_pack(
    path: str,
    *,
    presets_dir: str = "config/presets",
) -> StrategyPackLoadResult:
    """Load a versioned strategy pack file.

    Supported root shape (v1):
        {
          "schema_version": 1,
          "include_presets": ["trend_pullback_v1", ...],
          "strategies": [ {StrategySpec fields...}, ... ]
        }

    Back-compat:
    - Missing schema_version => defaults to 1 with warning
    - Root shape {"strategies": [...]} is still accepted

    Never raises.
    """
    errors: List[str] = []
    warnings: List[str] = []
    include_presets: List[str] = []
    loaded_presets: List[str] = []
    missing_presets: List[str] = []
    invalid_enabled: List[Dict[str, Any]] = []

    # Per-strategy diagnostics
    strategy_warnings: Dict[str, List[str]] = {}
    unknown_detectors_by_strategy: Dict[str, List[str]] = {}
    unknown_detector_suggestions_by_strategy: Dict[str, Dict[str, List[str]]] = {}
    disabled_unknown_detectors: Dict[str, List[str]] = {}

    # Auto-fix patch suggestions
    unknown_detector_autofix_patches: List[Dict[str, Any]] = []

    strict_detectors = _env_flag("STRICT_STRATEGY_DETECTORS", default=False)

    autofix_threshold = _safe_float(os.getenv("UNKNOWN_DETECTOR_AUTOFIX_THRESHOLD", "0.85"), 0.85)
    patch_suggestions_path = os.getenv("PATCH_SUGGESTIONS_PATH", "state/patch_suggestions.json")

    aliases_path = os.getenv("DETECTOR_ALIASES_PATH", "config/detector_aliases.json")
    detector_aliases = _load_detector_aliases(str(aliases_path))

    data, err = _safe_read_json_file(path)
    if err or not data:
        return StrategyPackLoadResult(
            schema_version=1,
            include_presets=[],
            loaded_presets=[],
            missing_presets=[],
            strategies=[],
            invalid_enabled=[],
            errors=[err or "INVALID_STRATEGY_FILE"],
            warnings=[],
            strategy_warnings={},
            unknown_detectors_by_strategy={},
            unknown_detector_suggestions_by_strategy={},
            disabled_unknown_detectors={},
            unknown_detector_autofix_patches=[],
        )

    schema_version = _coerce_schema_version(data.get("schema_version"))
    if schema_version is None:
        schema_version = 1
        warnings.append("SCHEMA_VERSION_MISSING_DEFAULT_1")

    if int(schema_version) != 1:
        errors.append("UNSUPPORTED_SCHEMA_VERSION")
        return StrategyPackLoadResult(
            schema_version=int(schema_version),
            include_presets=[],
            loaded_presets=[],
            missing_presets=[],
            strategies=[],
            invalid_enabled=[],
            errors=errors,
            warnings=warnings,
            strategy_warnings={},
            unknown_detectors_by_strategy={},
            unknown_detector_suggestions_by_strategy={},
            disabled_unknown_detectors={},
            unknown_detector_autofix_patches=[],
        )

    include_presets = _coerce_str_list(data.get("include_presets"))

    raw_strategies = data.get("strategies")
    if not isinstance(raw_strategies, list):
        raw_strategies = []
        if "strategies" in data:
            errors.append("BAD_STRATEGIES_SHAPE")

    preset_strategies: List[Dict[str, Any]] = []
    for pid in include_presets:
        preset_items, perr = _load_preset_pack_strategy_dicts(pid, presets_dir=presets_dir)
        if perr or not preset_items:
            missing_presets.append(pid)
            errors.append(f"PRESET:{pid}:{perr or 'LOAD_FAILED'}")
            continue
        loaded_presets.append(pid)
        preset_strategies.extend([x for x in preset_items if isinstance(x, dict)])

    # Merge precedence: presets first, then user strategies.
    merged: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}

    def _apply_item(item: Dict[str, Any]) -> None:
        sid = str(item.get("strategy_id") or "").strip()
        if sid:
            by_id[sid] = dict(item)
        else:
            merged.append(dict(item))

    for it in preset_strategies:
        _apply_item(it)
    for it in raw_strategies:
        if isinstance(it, dict):
            _apply_item(it)

    # Stable order: preset/user overrides resolved by dict; output sorted by strategy_id.
    for sid in sorted(by_id.keys()):
        merged.append(by_id[sid])

    try:
        known_detectors = set(detector_registry.list_detectors())
    except Exception:
        known_detectors = set()

    out: List[StrategySpec] = []
    for raw in merged:
        if not isinstance(raw, dict):
            continue

        # Params validation/truncation is non-fatal.
        raw2 = dict(raw)
        detector_params_raw = raw2.get("detector_params")
        family_params_raw = raw2.get("family_params")

        sanitized_detector_params: Dict[str, Dict[str, Any]] = {}
        if detector_params_raw is not None and not isinstance(detector_params_raw, dict):
            warnings.append("DETECTOR_PARAMS_BAD_SHAPE")
            detector_params_raw = None
        if isinstance(detector_params_raw, dict):
            for k, v in detector_params_raw.items():
                name = str(k or "").strip()
                if not name:
                    continue
                if known_detectors and name not in known_detectors:
                    warnings.append(f"UNKNOWN_DETECTOR_PARAMS:{name}")
                    continue
                if not isinstance(v, dict):
                    warnings.append(f"DETECTOR_PARAMS_IGNORED_NOT_OBJECT:{name}")
                    continue
                sv, truncated = sanitize_params(v)
                if truncated:
                    warnings.append(f"DETECTOR_PARAMS_TRUNCATED:{name}")
                if isinstance(sv, dict):
                    sanitized_detector_params[name] = sv

        sanitized_family_params: Dict[str, Dict[str, Any]] = {}
        if family_params_raw is not None and not isinstance(family_params_raw, dict):
            warnings.append("FAMILY_PARAMS_BAD_SHAPE")
            family_params_raw = None
        if isinstance(family_params_raw, dict):
            for k, v in family_params_raw.items():
                fam = str(k or "").strip()
                if not fam:
                    continue
                if not isinstance(v, dict):
                    warnings.append(f"FAMILY_PARAMS_IGNORED_NOT_OBJECT:{fam}")
                    continue
                sv, truncated = sanitize_params(v)
                if truncated:
                    warnings.append(f"FAMILY_PARAMS_TRUNCATED:{fam}")
                if isinstance(sv, dict):
                    sanitized_family_params[fam] = sv

        raw2["detector_params"] = sanitized_detector_params
        raw2["family_params"] = sanitized_family_params

        # Track enabled flag from raw dict for reporting even if parsing fails.
        enabled_flag = _coerce_bool(raw.get("enabled"), True)

        spec, spec_errors = StrategySpec.from_dict(raw2)
        if spec is None or spec_errors:
            if enabled_flag:
                invalid_enabled.append(
                    {
                        "strategy_id": str(raw.get("strategy_id") or "").strip() or "(missing)",
                        "errors": list(spec_errors or []),
                    }
                )
            continue

        if not spec.enabled:
            continue

        # Drop unknown detectors.
        # Resolve detectors: case-insensitive / normalization / aliases.
        requested = list(spec.detectors or [])
        resolved_result = resolve_detector_names(
            requested,
            list(known_detectors or []),
            aliases=detector_aliases,
            max_suggestions=3,
        )
        filtered = list(resolved_result.resolved)
        dropped = list(resolved_result.unknown)

        sid = str(spec.strategy_id or "").strip() or "(missing)"
        if resolved_result.alias_applied:
            lst = strategy_warnings.get(sid) or []
            for old, new in resolved_result.alias_applied.items():
                msg = f"DETECTOR_ALIAS_APPLIED:{old}->{new}"
                lst.append(msg)
                warnings.append(f"STRATEGY:{sid}:{msg}")
            strategy_warnings[sid] = lst

        if dropped:
            unknown_detectors_by_strategy[sid] = list(dropped)
            unknown_detector_suggestions_by_strategy[sid] = dict(resolved_result.suggestions or {})
            lst = strategy_warnings.get(sid) or []

            # High-confidence auto-fix patch suggestion (detectors only)
            replacements: Dict[str, str] = {}
            scored = (resolved_result.suggestions_scored or {})
            for unk in dropped:
                top = (scored.get(unk) or [])
                if not top:
                    continue
                best_name, best_score = top[0]
                if best_name and float(best_score) >= float(autofix_threshold):
                    replacements[str(unk)] = str(best_name)

            if replacements:
                before_dets = list(requested)
                after_dets = []
                for d in before_dets:
                    ds = str(d or "").strip()
                    if ds in replacements:
                        after_dets.append(replacements[ds])
                    else:
                        after_dets.append(ds)
                after_dets = _dedupe_preserve_order(after_dets)
                if after_dets and before_dets != after_dets:
                    date = _utc_date()
                    patch_id = _stable_patch_id(
                        patch_type="FIX_UNKNOWN_DETECTORS",
                        date=date,
                        strategy_id=sid,
                        replacements=replacements,
                    )
                    item = {
                        "patch_id": patch_id,
                        "date": date,
                        "patch_type": "FIX_UNKNOWN_DETECTORS",
                        "strategy_id": sid,
                        "strategy_ids": [sid],
                        "replacements": dict(replacements),
                        "changes": {"detectors": {"from": before_dets, "to": after_dets}},
                        "before_snapshot": {"detectors": before_dets},
                        "after_snapshot": {"detectors": after_dets},
                        "dry_run_preview": f"detectors: {json.dumps(before_dets, ensure_ascii=False)} -> {json.dumps(after_dets, ensure_ascii=False)}",
                    }
                    unknown_detector_autofix_patches.append(item)

            for name in dropped:
                sugg = (resolved_result.suggestions or {}).get(name) or []
                if sugg:
                    hint = "|".join([str(x) for x in sugg[:3]])
                    lst.append(f"UNKNOWN_DETECTOR:{name} SUGGEST:{hint}")
                    warnings.append(f"STRATEGY:{sid}:UNKNOWN_DETECTOR:{name}:SUGGEST:{hint}")
                else:
                    lst.append(f"UNKNOWN_DETECTOR:{name}")
                    warnings.append(f"STRATEGY:{sid}:UNKNOWN_DETECTOR:{name}")
            strategy_warnings[sid] = lst

            if strict_detectors:
                disabled_unknown_detectors[sid] = list(dropped)
                # Do not include this strategy in-memory.
                continue

        if filtered != list(spec.detectors):
            dct = spec.to_dict()
            dct["detectors"] = filtered
            spec2, errors2 = StrategySpec.from_dict(dct)
            if spec2 is not None and not errors2:
                spec = spec2

        out.append(spec)

    # Persist auto-fix patch suggestions (best-effort, non-fatal).
    try:
        _persist_patch_suggestions_items(str(patch_suggestions_path), list(unknown_detector_autofix_patches))
    except Exception:
        pass

    return StrategyPackLoadResult(
        schema_version=int(schema_version),
        include_presets=list(include_presets),
        loaded_presets=list(loaded_presets),
        missing_presets=list(missing_presets),
        strategies=out,
        invalid_enabled=invalid_enabled,
        errors=errors,
        warnings=warnings,
        strategy_warnings=strategy_warnings,
        unknown_detectors_by_strategy=unknown_detectors_by_strategy,
        unknown_detector_suggestions_by_strategy=unknown_detector_suggestions_by_strategy,
        disabled_unknown_detectors=disabled_unknown_detectors,
        unknown_detector_autofix_patches=unknown_detector_autofix_patches,
    )


def load_strategies(path: str) -> List[StrategySpec]:
    """Load strategies from a JSON file.

    Required JSON shape:
        {"strategies": [ {StrategySpec fields...}, ... ]}

    V1 behavior:
    - Never raises (bad JSON => returns empty list)
    - Missing optional fields => defaults (StrategySpec.from_dict)
    - Unknown detector names => drop + continue
    """
    return load_strategy_pack(path).strategies
