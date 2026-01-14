from __future__ import annotations

from typing import Any, Dict, List, Optional


# Preset packs: StrategySpec v1 dicts.
# These are intentionally minimal and rely on existing detector plugin names.


def _det_enabled(*names: str) -> Dict[str, Any]:
    return {n: {"enabled": True} for n in names}


PRESETS: Dict[str, Dict[str, Any]] = {
    "range_reversal_v1": {
        "strategy_id": "range_reversal_v1",
        "enabled": True,
        "engine_version": "indicator_free_v1",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 2.5,
        "min_score": 0.9,
        "allowed_regimes": ["RANGE", "CHOP"],
        "epsilon": 0.15,
        "family_bonus": 0.25,
        "detectors": _det_enabled("range_box_edge", "sr_bounce", "fakeout_trap"),
        "detector_weight_overrides": {},
    },
    "trend_pullback_v1": {
        "strategy_id": "trend_pullback_v1",
        "enabled": True,
        "engine_version": "indicator_free_v1",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 3.0,
        "min_score": 1.0,
        "allowed_regimes": ["TREND_BULL", "TREND_BEAR"],
        "epsilon": 0.15,
        "family_bonus": 0.25,
        "detectors": _det_enabled("structure_trend", "fibo_retrace_confluence", "sr_role_reversal"),
        "detector_weight_overrides": {},
    },
    "breakout_retest_v1": {
        "strategy_id": "breakout_retest_v1",
        "enabled": True,
        "engine_version": "indicator_free_v1",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 2.5,
        "min_score": 1.0,
        "allowed_regimes": ["TREND_BULL", "TREND_BEAR"],
        "epsilon": 0.15,
        "family_bonus": 0.25,
        "detectors": _det_enabled("sr_breakout", "sr_role_reversal", "structure_trend"),
        "detector_weight_overrides": {},
    },
    "trend_reversal_v1": {
        "strategy_id": "trend_reversal_v1",
        "enabled": True,
        "engine_version": "indicator_free_v1",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 2.0,
        "min_score": 1.5,
        "allowed_regimes": ["TREND", "RANGE"],
        "epsilon": 0.05,
        "family_bonus": 0.30,
        "detectors": _det_enabled(
            "break_retest",
            "breakout_retest_entry",
            "double_top_bottom",
            "head_shoulders",
            "fibo_retrace_confluence",
        ),
        "detector_weight_overrides": {
            "break_retest": 1.3,
            "breakout_retest_entry": 1.2,
            "double_top_bottom": 1.4,
            "head_shoulders": 1.5,
            "fibo_retrace_confluence": 1.1,
        },
    },
}


def list_preset_ids() -> List[str]:
    return sorted(PRESETS.keys())


def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    if not preset_id:
        return None
    return dict(PRESETS.get(str(preset_id).strip()) or {}) or None


def apply_preset(preset_id: str, overrides: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    base = get_preset(preset_id)
    if not base:
        return None
    merged: Dict[str, Any] = dict(base)
    for k, v in (overrides or {}).items():
        if k in ("preset", "preset_id"):
            continue
        merged[k] = v
    return merged
