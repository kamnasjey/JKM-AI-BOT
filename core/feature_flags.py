from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Set


def _split_tokens(s: str) -> list[str]:
    raw = (s or "").replace(";", ",").replace(" ", ",")
    out: list[str] = []
    for tok in raw.split(","):
        t = str(tok or "").strip()
        if t:
            out.append(t)
    return out


def _coerce_bool(v: Any, default: bool = False) -> bool:
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


@dataclass(frozen=True)
class FeatureFlags:
    """Simple feature flag container.

    Sources:
    - ENV: FEATURE_FLAGS="flag_a,flag_b" and DISABLE_FEATURE_FLAGS="flag_a"
    - ENV bool shorthands: CANARY_MODE=1, SHADOW_ALL_DETECTORS=1
    - Config dict: feature_flags={"flag_a": true} or feature_flags=["flag_a"]

    Default is stable: flags are OFF unless explicitly enabled.
    """

    enabled: Set[str] = field(default_factory=set)
    canary_mode: bool = False
    shadow_all_detectors: bool = False

    @staticmethod
    def from_sources(*, config: Optional[Any] = None, env: Optional[Dict[str, str]] = None) -> "FeatureFlags":
        env_map: Dict[str, str] = dict(env) if isinstance(env, dict) else dict(os.environ)

        enabled: Set[str] = set()

        # 1) ENV list
        for tok in _split_tokens(env_map.get("FEATURE_FLAGS", "")):
            if "=" in tok:
                k, v = tok.split("=", 1)
                if _coerce_bool(v, False):
                    enabled.add(str(k).strip())
            else:
                enabled.add(tok)

        # 2) Config
        if isinstance(config, dict):
            for k, v in config.items():
                if _coerce_bool(v, False):
                    enabled.add(str(k).strip())
        elif isinstance(config, (list, tuple, set)):
            for it in list(config):
                s = str(it or "").strip()
                if s:
                    enabled.add(s)

        # 3) Explicit disables
        for tok in _split_tokens(env_map.get("DISABLE_FEATURE_FLAGS", "")):
            enabled.discard(tok)

        # Canonicalize
        enabled = {str(x).strip() for x in enabled if str(x).strip()}

        # 4) Built-in convenience toggles (keep backward compat)
        canary_mode = _coerce_bool(env_map.get("CANARY_MODE"), False) or ("canary_mode" in enabled)

        shadow_all_detectors = (
            _coerce_bool(env_map.get("SHADOW_ALL_DETECTORS"), False)
            or ("shadow_all_detectors" in enabled)
        )

        return FeatureFlags(
            enabled=enabled,
            canary_mode=bool(canary_mode),
            shadow_all_detectors=bool(shadow_all_detectors),
        )

    def is_enabled(self, flag: str) -> bool:
        return str(flag or "").strip() in self.enabled

    def as_dict(self) -> Dict[str, Any]:
        return {
            "enabled": sorted(self.enabled),
            "canary_mode": bool(self.canary_mode),
            "shadow_all_detectors": bool(self.shadow_all_detectors),
        }


def canary_detector_list(*, config: Optional[Dict[str, Any]] = None, env: Optional[Dict[str, str]] = None) -> list[str]:
    env_map: Dict[str, str] = dict(env) if isinstance(env, dict) else dict(os.environ)
    out: list[str] = []

    # ENV: CANARY_DETECTORS="a,b,c"
    out.extend(_split_tokens(env_map.get("CANARY_DETECTORS", "")))

    # Config: {"canary_detectors": ["a", "b"]}
    if isinstance(config, dict):
        items = config.get("canary_detectors")
        if isinstance(items, (list, tuple)):
            for it in items:
                s = str(it or "").strip()
                if s:
                    out.append(s)

    # De-dupe preserve order
    seen: Set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq
