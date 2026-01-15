"""
Detector plugins for the trading engine.

UNIFIED DETECTOR SYSTEM (24 detectors)
--------------------------------------
This package unifies all detectors into a single registry:

Legacy (11 via adapter):
  - trend_fibo, break_retest, sr_break_close, engulf_at_level
  - breakout_retest_entry, triangle_breakout_close, flag_pennant
  - double_top_bottom, head_shoulders, rectangle_range_edge
  - price_momentum_weakening

New engines (13):
  Gates (3): gate_regime, gate_volatility, gate_drift_sentinel
  Momentum (2): compression_expansion, momentum_continuation  
  Mean Rev (1): mean_reversion_snapback
  Candles (2): pinbar_at_level, doji
  Fibo (2): fibo_retrace_confluence, fibo_extension
  S/R (2): sr_bounce, sr_role_reversal
  Range (1): fakeout_trap

Merged/Disabled:
  - pinbar -> use pinbar_at_level (has level check)
  - engulfing -> use engulf_at_level (has level check)
  - sr_breakout -> use sr_break_close (more detailed)
  - range_box_edge -> use rectangle_range_edge (legacy is better)
  - fibo_retrace -> use fibo_retrace_confluence (has S/R confluence)
"""

from .base import BaseDetector, DetectorResult, DetectorGroup, DetectorMeta
from .registry import detector_registry, register_detector

# Import NEW detector modules (these register via @register_detector decorator)
from . import gates          # gate_regime, gate_volatility, gate_drift_sentinel
from . import momentum       # compression_expansion, momentum_continuation
from . import mean_reversion # mean_reversion_snapback
from . import candles        # pinbar_at_level, doji (pinbar, engulfing disabled)
from . import fibo           # fibo_retrace_confluence, fibo_extension (fibo_retrace disabled)
from . import sr             # sr_bounce, sr_role_reversal (sr_breakout disabled)
from . import range          # fakeout_trap (range_box_edge disabled)

# Import and register legacy detectors (11 remaining - 4 duplicates skipped)
from .legacy_adapter import ensure_legacy_registered, LegacyDetectorAdapter
ensure_legacy_registered()

__all__ = [
    "BaseDetector",
    "DetectorResult",
    "DetectorGroup",
    "DetectorMeta",
    "detector_registry",
    "register_detector",
    "LegacyDetectorAdapter",
]