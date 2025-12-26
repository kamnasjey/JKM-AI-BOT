from __future__ import annotations

from typing import Dict


# Canonical (stable) metrics alert codes.
OK_RATE_LOW = "OK_RATE_LOW"
AVG_RR_LOW = "AVG_RR_LOW"
COOLDOWN_BLOCKS_HIGH = "COOLDOWN_BLOCKS_HIGH"
TOP_REASON_DOMINANCE = "TOP_REASON_DOMINANCE"


# Historical aliases -> canonical.
_ALERT_CODE_ALIASES: Dict[str, str] = {
    # OK rate variants
    "OK_RATE_BELOW_MIN": OK_RATE_LOW,
    "OK_RATE_MIN": OK_RATE_LOW,
    "OKRATE_LOW": OK_RATE_LOW,
    "OKRATE_BELOW_MIN": OK_RATE_LOW,
    # Avg RR variants
    "AVG_RR_BELOW_MIN": AVG_RR_LOW,
    "AVG_RR_MIN": AVG_RR_LOW,
    # Cooldown blocks variants
    "COOLDOWN_BLOCKS_TOO_HIGH": COOLDOWN_BLOCKS_HIGH,
    # Top-reason dominance variants
    "NO_HITS_DOMINANT": TOP_REASON_DOMINANCE,
    "NO_HITS_DOMINANCE": TOP_REASON_DOMINANCE,
    "TOP_REASON_DOMINANT": TOP_REASON_DOMINANCE,
}


def canonicalize_alert_code(code: str) -> str:
    """Return canonical alert code.

    - Accepts legacy variants (aliases) and normalizes to a single stable code.
    - Output is always uppercase and never empty.
    """
    raw = str(code or "").strip()
    if not raw:
        return "NA"

    up = raw.upper()
    return str(_ALERT_CODE_ALIASES.get(up, up))
