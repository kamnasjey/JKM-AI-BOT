from __future__ import annotations

from typing import Any, Dict, List


def default_trend_reversal_strategy() -> Dict[str, Any]:
    # Indicator-free, structure/pattern based.
    # Kept inline so the engine can function even if config files are missing.
    return {
        "strategy_id": "trend_reversal_v1",
        "name": "Trend Reversal (Default)",
        "enabled": True,
        "priority": 60,
        "engine_version": "indicator_free_v1",
        "description": "Default strategy for new users: trend reversal patterns + break/retest.",
        "min_score": 1.5,
        "min_rr": 2.0,
        "allowed_regimes": ["TREND", "RANGE"],
        "detectors": [
            "break_retest",
            "breakout_retest_entry",
            "double_top_bottom",
            "head_shoulders",
            "fibo_retrace_confluence",
        ],
        "detector_weights": {
            "break_retest": 1.3,
            "breakout_retest_entry": 1.2,
            "double_top_bottom": 1.4,
            "head_shoulders": 1.5,
            "fibo_retrace_confluence": 1.1,
        },
        "family_weights": {"structure": 1.3, "sr": 1.1, "fibo": 1.0},
        "conflict_epsilon": 0.05,
        "confluence_bonus_per_family": 0.30,
    }


def get_default_user_strategies() -> List[Dict[str, Any]]:
    return [default_trend_reversal_strategy()]
