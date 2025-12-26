from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


STABLE_PAIR_NONE_REASONS = {
    "NO_HITS",
    "SCORE_BELOW_MIN",
    "CONFLICT_SCORE",
    "NO_DETECTORS_FOR_REGIME",
    "RR_BELOW_MIN",
    "COOLDOWN_ACTIVE",
    "DAILY_LIMIT_REACHED",
    "PROFILE_INVALID",
    "STRATEGY_INVALID",
    "UNKNOWN_ERROR",
}


_ALIAS_TO_STABLE = {
    # Governance
    "COOLDOWN_BLOCK": "COOLDOWN_ACTIVE",
    "COOLDOWN_ACTIVE": "COOLDOWN_ACTIVE",
    "DAILY_LIMIT_BLOCK": "DAILY_LIMIT_REACHED",
    "DAILY_LIMIT_REACHED": "DAILY_LIMIT_REACHED",
    "daily_limit": "DAILY_LIMIT_REACHED",

    # Engine / detector outcome
    "no_match": "NO_HITS",
    "NO_SIGNALS_FROM_DETECTORS": "NO_HITS",
    "NO_HITS": "NO_HITS",
    "NO_DETECTORS_FOR_REGIME": "NO_DETECTORS_FOR_REGIME",

    # Score/quality gates
    "low_score": "SCORE_BELOW_MIN",
    "SCORE_BELOW_MIN": "SCORE_BELOW_MIN",
    "conflict": "CONFLICT_SCORE",
    "CONFLICT_SCORE": "CONFLICT_SCORE",
    "RR_BELOW_MIN": "RR_BELOW_MIN",

    # Validation
    "PROFILE_INVALID": "PROFILE_INVALID",
    "STRATEGY_INVALID": "STRATEGY_INVALID",

    # Generic fallbacks / non-stable internal reasons
    "data_gap": "UNKNOWN_ERROR",
    "no_m5": "UNKNOWN_ERROR",
}


_PRIORITY = [
    "PROFILE_INVALID",
    "STRATEGY_INVALID",
    "NO_DETECTORS_FOR_REGIME",
    "NO_HITS",
    "SCORE_BELOW_MIN",
    "RR_BELOW_MIN",
    "COOLDOWN_ACTIVE",
    "DAILY_LIMIT_REACHED",
    "CONFLICT_SCORE",
    "UNKNOWN_ERROR",
]


def normalize_pair_none_reason(reasons: Optional[List[str]]) -> str:
    """Map internal reason strings to stable PAIR_NONE reason codes.

    Outputs are restricted to `STABLE_PAIR_NONE_REASONS`.
    Legacy/internal strings are accepted as input aliases only.
    """
    if not isinstance(reasons, list) or not reasons:
        return "NO_HITS"

    mapped: List[str] = []
    for r in reasons:
        if r is None:
            continue
        s = str(r)

        # Normalize SCORE_BELOW_MIN|x<y => SCORE_BELOW_MIN
        if s.startswith("SCORE_BELOW_MIN"):
            s = "SCORE_BELOW_MIN"

        mapped.append(_ALIAS_TO_STABLE.get(s, s))

    # Special preference: if NO_HITS appears anywhere, treat as NO_HITS.
    if "NO_HITS" in mapped:
        return "NO_HITS"

    for p in _PRIORITY:
        if p in mapped:
            return p

    # Final safety: never emit unknown outputs.
    return "UNKNOWN_ERROR"


def build_governance_evidence(
    *,
    strategy_id: Optional[str] = None,
    symbol: Optional[str] = None,
    tf: Optional[str] = None,
    direction: Optional[str] = None,
    last_sent_ts: Optional[float] = None,
    cooldown_minutes: Optional[int] = None,
    cooldown_remaining_s: Optional[float] = None,
    sent_today_count: Optional[int] = None,
    daily_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Return NA-safe governance evidence with stable keys.

    Always includes all keys; missing values are the string "NA".
    """

    def _na(v: Any) -> Any:
        return "NA" if v is None else v

    # Prefer 0 over NA for counters.
    if sent_today_count is None:
        sent_today_count = 0

    return {
        "strategy_id": _na((str(strategy_id) if strategy_id is not None else None)),
        "symbol": _na((str(symbol).upper() if symbol is not None else None)),
        "tf": _na((str(tf).upper() if tf is not None else None)),
        "direction": _na((str(direction).upper() if direction is not None else None)),
        "last_sent_ts": _na(last_sent_ts),
        "cooldown_minutes": _na(cooldown_minutes),
        "cooldown_remaining_s": _na(cooldown_remaining_s),
        "sent_today_count": int(sent_today_count),
        "daily_limit": _na(daily_limit),
    }
