"""Detectors module for trading signal detection."""

from .base import BaseDetector, DetectorConfig, DetectorSignal
from .registry import DETECTOR_REGISTRY, get_detector

__all__ = [
    "BaseDetector",
    "DetectorConfig",
    "DetectorSignal",
    "DETECTOR_REGISTRY",
    "get_detector",
]
