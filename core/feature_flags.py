"""core.feature_flags

Two feature-flag systems live here for backwards compatibility:

1) Legacy FF_* flags via :func:`check_flag` / :func:`is_enabled`
   - Used by older engine paths.
   - Values come from env vars named exactly like the flag (e.g. FF_DETECTOR_SAFE_MODE).

2) New plugin/engine flags via :class:`FeatureFlags`
   - Used by the detectors plugin runner and strategy engine.
   - Default is conservative OFF unless explicitly enabled.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set


def _coerce_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _parse_flag_list(v: Any) -> List[str]:
    """Best-effort parse for FEATURE_FLAGS / config inputs.

    Supports:
    - list[str]
    - comma-separated string
    - JSON list in string form
    """
    if v is None:
        return []
    if isinstance(v, (list, tuple, set, frozenset)):
        return [str(x).strip() for x in list(v) if str(x or "").strip()]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        # JSON list?
        if s.startswith("[") and s.endswith("]"):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    return [str(x).strip() for x in arr if str(x or "").strip()]
            except Exception:
                pass
        # CSV
        return [x.strip() for x in s.split(",") if x.strip()]
    return []


@dataclass(frozen=True)
class FeatureFlags:
    """Opt-in flags for the plugin engine.

    - Default: OFF (no flags enabled)
    - `DISABLE_FEATURE_FLAGS=1`: forces all OFF
    - `FEATURE_FLAGS`: enables flags (csv or JSON list)
    - `CANARY_MODE=1`: enables canary mode
    - `SHADOW_ALL_DETECTORS=1`: runs shadow evaluation for detector coverage
    """

    enabled: frozenset[str]
    canary_mode: bool = False
    shadow_all_detectors: bool = False
    disabled: bool = False

    @classmethod
    def from_sources(cls, config: Optional[Any] = None) -> "FeatureFlags":
        disabled = _coerce_bool(os.getenv("DISABLE_FEATURE_FLAGS"), False)

        enabled: Set[str] = set()

        # 1) Config input (profile['feature_flags'])
        if isinstance(config, dict):
            # Accepted forms:
            # - {"enabled": ["A", "B"]}
            # - {"A": true, "B": false}
            enabled |= set(_parse_flag_list(config.get("enabled")))
            for k, v in list(config.items()):
                if k in ("enabled", "canary_mode", "shadow_all_detectors", "disabled"):
                    continue
                if _coerce_bool(v, False):
                    enabled.add(str(k))
        else:
            enabled |= set(_parse_flag_list(config))

        # 2) Env input
        enabled |= set(_parse_flag_list(os.getenv("FEATURE_FLAGS")))

        # 3) Modes (env overrides config)
        canary_mode = False
        shadow_all = False
        if isinstance(config, dict):
            canary_mode = _coerce_bool(config.get("canary_mode"), False)
            shadow_all = _coerce_bool(config.get("shadow_all_detectors"), False)

        canary_mode = _coerce_bool(os.getenv("CANARY_MODE"), canary_mode)
        shadow_all = _coerce_bool(os.getenv("SHADOW_ALL_DETECTORS"), shadow_all)

        if disabled:
            enabled = set()
            canary_mode = False
            shadow_all = False

        return cls(
            enabled=frozenset(sorted({str(x).strip() for x in enabled if str(x).strip()})),
            canary_mode=bool(canary_mode),
            shadow_all_detectors=bool(shadow_all),
            disabled=bool(disabled),
        )

    def is_enabled(self, flag_name: str) -> bool:
        if self.disabled:
            return False
        name = str(flag_name or "").strip()
        if not name:
            return False
        return name in self.enabled

    def as_dict(self) -> Dict[str, Any]:
        return {
            "disabled": bool(self.disabled),
            "canary_mode": bool(self.canary_mode),
            "shadow_all_detectors": bool(self.shadow_all_detectors),
            "enabled": sorted(self.enabled),
        }


def canary_detector_list(*, config: Optional[Dict[str, Any]] = None) -> List[str]:
    """Return the canary detector allow-list.

    This is intentionally conservative and only enables explicitly listed detectors.
    """
    if not isinstance(config, dict):
        return []

    # Preferred: profile['canary_detectors']
    raw = config.get("canary_detectors")
    if raw is None and isinstance(config.get("feature_flags"), dict):
        raw = (config.get("feature_flags") or {}).get("canary_detectors")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(raw, (list, tuple, set, frozenset)):
        return [str(x).strip() for x in list(raw) if str(x or "").strip()]
    return []


# --- Legacy FF_* flags (backwards compatible) ---

# Define all available legacy flags and their defaults here.
DEFAULTS: Dict[str, bool] = {
    "FF_PUBLIC_SIGNALS_WRITE": True,  # Write to state/signals.jsonl
    "FF_SHADOW_EVAL": False,  # Run shadow dual-evaluation for arbitration
    "FF_NEW_DETECTORS_PACK": False,  # Enable experimental detectors
    "FF_DETECTOR_SAFE_MODE": True,  # Catch all detector exceptions (non-fatal)
}

_FLAGS_CACHE: Dict[str, bool] = {}


def reload_flags() -> None:
    """Reload legacy FF_* flags from env vars, overriding defaults."""
    _FLAGS_CACHE.clear()
    for key, default_val in DEFAULTS.items():
        env_val = os.getenv(key)
        if env_val is not None:
            _FLAGS_CACHE[key] = _coerce_bool(env_val, default_val)
        else:
            _FLAGS_CACHE[key] = default_val


def is_enabled(flag_name: str) -> bool:
    """Legacy FF_* flag check (unknown flags -> False)."""
    if not _FLAGS_CACHE:
        reload_flags()

    if flag_name not in DEFAULTS:
        logging.getLogger(__name__).warning(f"Unknown feature flag checked: {flag_name}")
        return False
    return _FLAGS_CACHE.get(flag_name, False)


def get_all_flags() -> Dict[str, bool]:
    """Returns a copy of all legacy FF_* flag states."""
    if not _FLAGS_CACHE:
        reload_flags()
    return dict(_FLAGS_CACHE)


def check_flag(flag_name: str) -> bool:
    """Alias for legacy :func:`is_enabled`."""
    return is_enabled(flag_name)
