"""
Detector plugins for the trading engine.

This package contains all detector implementations that work with
the primitive-based engine pipeline.
"""

# Import all detector modules to ensure registration
from . import sr
from . import candles
from . import fibo
from . import price_action
from . import range
from . import gates
from . import momentum
from . import mean_reversion

from .base import BaseDetector, DetectorResult, DetectorGroup
from .registry import detector_registry, register_detector

__all__ = [
    "BaseDetector",
    "DetectorResult",
    "DetectorGroup",
    "detector_registry",
    "register_detector",
]
