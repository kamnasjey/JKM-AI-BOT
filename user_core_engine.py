"""Backward-compatible re-export for the user core engine.

The canonical implementation now lives in `core.user_core_engine`.

Note: `import *` does not import underscore-prefixed names unless `__all__` is defined.
Some lightweight tests import a few internal helpers directly, so we re-export them explicitly.
"""

from core.user_core_engine import (  # type: ignore
	ScanResult,
	extract_strategy_configs,
	scan_pair_cached,
	scan_pair_cached_indicator_free,
	scan_pair_with_profile_verbose,
)
from core.user_core_engine import (  # type: ignore
	_analyze_trend_step,
	_check_fibo_step_dir,
	_find_swing_step,
	_validate_data_sufficiency,
)

__all__ = [
	"ScanResult",
	"extract_strategy_configs",
	"scan_pair_cached",
	"scan_pair_cached_indicator_free",
	"scan_pair_with_profile_verbose",
	"_validate_data_sufficiency",
	"_analyze_trend_step",
	"_find_swing_step",
	"_check_fibo_step_dir",
]
