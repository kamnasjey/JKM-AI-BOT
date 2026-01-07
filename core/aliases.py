"""
aliases.py
----------
Central source of truth for backward compatibility aliases.
Used to normalize detector names, reason codes, and schema fields
so that clients relying on old keys don't break when we rename things internally.
"""

from typing import Dict

# Map legacy detector names to current canonical names
DETECTOR_ALIASES: Dict[str, str] = {
    # Example: "fib_trend" -> "trend_fibo"
    # "old_name": "new_name"
    "fib_trend": "trend_fibo",
}

# Map legacy reason codes to current canonical codes
REASON_ALIASES: Dict[str, str] = {
    # Example: "rsi_div" -> "momentum_divergence"
}

def normalize_detector_name(name: str) -> str:
    """Returns canonical detector name."""
    return DETECTOR_ALIASES.get(name, name)

def normalize_reason_code(code: str) -> str:
    """Returns canonical reason code."""
    return REASON_ALIASES.get(code, code)
