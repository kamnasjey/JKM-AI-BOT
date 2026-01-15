"""
Detector plugins for the trading engine.

UNIFIED DETECTOR SYSTEM
-----------------------
This package unifies all detectors into a single registry:
- 15 legacy detectors (detectors/) 
- 6 new detectors (gates, momentum, mean_reversion)
- Total: 21 unique detectors

The legacy detectors are wrapped via LegacyDetectorAdapter to work
with the new pipeline architecture.
"""

from .base import BaseDetector, DetectorResult, DetectorGroup, DetectorMeta
from .registry import detector_registry, register_detector

# Import ONLY the new detector modules (gates, momentum, mean_reversion)
# These are the 6 NEW detectors not in legacy:
from . import gates          # gate_regime, gate_volatility, gate_drift_sentinel
from . import momentum       # compression_expansion, momentum_continuation  
from . import mean_reversion # mean_reversion_snapback

# Import and register legacy detectors (15 existing detectors)
from .legacy_adapter import ensure_legacy_registered, LegacyDetectorAdapter

# Auto-register legacy detectors when this package is imported
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