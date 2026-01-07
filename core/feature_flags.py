"""
feature_flags.py
----------------
Centralized feature flag management for the trading engine.
Loads flags from environment variables (prefix FF_) and provides defaults.
"""

import os
import logging
from typing import Dict, Any

# Define all available flags and their defaults here.
# This acts as the source of truth for flag existence.
DEFAULTS: Dict[str, bool] = {
    "FF_PUBLIC_SIGNALS_WRITE": True,   # Write to state/signals.jsonl
    "FF_SHADOW_EVAL": False,           # Run shadow dual-evaluation for arbitration
    "FF_NEW_DETECTORS_PACK": False,    # Enable experimental detectors
    "FF_DETECTOR_SAFE_MODE": True,     # Catch all detector exceptions (non-fatal)
}

_FLAGS_CACHE: Dict[str, bool] = {}

def reload_flags() -> None:
    """Reloads flags from environment variables, overriding defaults."""
    _FLAGS_CACHE.clear()
    for key, default_val in DEFAULTS.items():
        # potential env var name: e.g. "FF_SHADOW_EVAL"
        env_val = os.getenv(key)
        if env_val is not None:
            # Parse typical boolean strings
            low = env_val.lower().strip()
            is_true = low in ("1", "true", "yes", "on")
            _FLAGS_CACHE[key] = is_true
        else:
            _FLAGS_CACHE[key] = default_val

def is_enabled(flag_name: str) -> bool:
    """
    Check if a feature flag is enabled.
    
    Args:
        flag_name: The name of the flag (must be in DEFAULTS).
        
    Returns:
        bool: True if enabled, False otherwise. Defaults to False if unknown flag.
    """
    if not _FLAGS_CACHE:
        reload_flags()
        
    # If strictly strictly requiring definition in DEFAULTS:
    if flag_name not in DEFAULTS:
        logging.getLogger(__name__).warning(f"Unknown feature flag checked: {flag_name}")
        return False
        
    return _FLAGS_CACHE.get(flag_name, False)

def get_all_flags() -> Dict[str, bool]:
    """Returns a copy of all current flag states."""
    if not _FLAGS_CACHE:
        reload_flags()
    return dict(_FLAGS_CACHE)

def check_flag(flag_name: str) -> bool:
    """Alias for is_enabled."""
    return is_enabled(flag_name)
