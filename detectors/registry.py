"""
registry.py
-----------
Detector registry for enable/disable mechanism.
"""

from typing import Any, Dict, Optional, Type

from .base import BaseDetector, DetectorConfig
from .break_retest import BreakRetestDetector
from .breakout_retest_entry import BreakoutRetestEntryDetector
from .double_top_bottom import DoubleTopBottomDetector
from .engulf_at_level import EngulfAtLevelDetector
from .fakeout_trap import FakeoutTrapDetector
from .flag_pennant import FlagPennantDetector
from .head_shoulders import HeadShouldersDetector
from .pinbar_at_level import PinbarAtLevelDetector
from .fibo_retrace_confluence import FiboRetraceConfluenceDetector
from .price_momentum_weakening import PriceMomentumWeakeningDetector
from .rectangle_range_edge import RectangleRangeEdgeDetector
from .sr_break_close import SRBreakCloseDetector
from .sr_role_reversal import SRRoleReversalDetector
from .triangle_breakout_close import TriangleBreakoutCloseDetector
from .trend_fibo import TrendFiboDetector


# Global detector registry
DETECTOR_REGISTRY: Dict[str, Type[BaseDetector]] = {
    "trend_fibo": TrendFiboDetector,
    "break_retest": BreakRetestDetector,
    "pinbar_at_level": PinbarAtLevelDetector,
    "sr_break_close": SRBreakCloseDetector,
    "sr_role_reversal": SRRoleReversalDetector,
    "engulf_at_level": EngulfAtLevelDetector,
    "breakout_retest_entry": BreakoutRetestEntryDetector,
    "fakeout_trap": FakeoutTrapDetector,
    "fibo_retrace_confluence": FiboRetraceConfluenceDetector,
    "triangle_breakout_close": TriangleBreakoutCloseDetector,
    "flag_pennant": FlagPennantDetector,
    "double_top_bottom": DoubleTopBottomDetector,
    "head_shoulders": HeadShouldersDetector,
    "rectangle_range_edge": RectangleRangeEdgeDetector,
    "price_momentum_weakening": PriceMomentumWeakeningDetector,
}


def get_detector(name: str, config: Optional[DetectorConfig] = None) -> Optional[BaseDetector]:
    """
    Get detector instance by name.
    
    Args:
        name: Detector name
        config: Optional detector configuration
        
    Returns:
        Detector instance or None if not found
    """
    detector_class = DETECTOR_REGISTRY.get(name)
    if detector_class is None:
        return None
    
    return detector_class(config=config)


def get_enabled_detectors(
    detector_configs: Dict[str, Dict],
    default_enabled: Optional[list] = None,
) -> Dict[str, BaseDetector]:
    """
    Get all enabled detectors from user configuration.
    
    Args:
        detector_configs: Dict mapping detector name to config dict
        default_enabled: List of detector names to enable by default
        
    Returns:
        Dict of enabled detector instances
    """
    if default_enabled is None:
        default_enabled = ["trend_fibo"]  # Default: only trend_fibo enabled
    
    enabled = {}
    
    # If no detector config provided, use defaults
    if not detector_configs:
        for name in default_enabled:
            detector = get_detector(name, DetectorConfig(enabled=True), wrap_safe=True)
            if detector:
                enabled[name] = detector
        return enabled
    
    
    # Process user-provided detector configs
    for name, cfg in detector_configs.items():
        if not isinstance(cfg, dict):
            continue
        
        is_enabled = cfg.get("enabled", False)
        if not is_enabled:
            continue
        
        params = cfg.get("params", {})
        detector_config = DetectorConfig(enabled=True, params=params)
        detector = get_detector(name, detector_config, wrap_safe=True)
        
        if detector:
            enabled[name] = detector
    
    return enabled


class SafeDetectorWrapper(BaseDetector):
    """
    Wraps any detector to ensure it never crashes the engine.
    Catches exceptions and returns a 'miss' with error metadata.
    """
    def __init__(self, inner: BaseDetector):
        self.inner = inner
        # Proxy metadata
        self.name = inner.name
        self.doc = inner.doc
        self.params_schema = inner.params_schema
        self.examples = inner.examples
        # Proxy config
        self.config = inner.config

    def detect(self, *args, **kwargs) -> Optional[Any]: # DetectorSignal
        try:
            return self.inner.detect(*args, **kwargs)
        except Exception as e:
            # Import here to avoid circular init if flags uses logging which uses something else...
            # But core.feature_flags is safe.
            from core.feature_flags import check_flag
            
            # If safety mode is OFF (rare/debug), re-raise
            if not check_flag("FF_DETECTOR_SAFE_MODE"):
                raise
                
            # Otherwise, log and swallow
            from engine.utils.logging_utils import log_kv
            import logging
            
            log_kv(
                logging.getLogger(f"SafeWrapper_{self.name}"),
                "DETECTOR_RUNTIME_ERROR",
                detector=self.name,
                error=str(e),
                severity="error"
            )
            # Return None (no signal) effectively swallowing the error
            return None

    # Proxy other methods if necessary, but BaseDetector methods are simple.
    def is_enabled(self) -> bool:
        return self.inner.is_enabled()
    
    def get_doc(self) -> str:
        return self.inner.get_doc()
    
    def get_params_schema(self) -> Dict[str, Any]:
        return self.inner.get_params_schema()
    
    def get_examples(self) -> list:
        return self.inner.get_examples()


def _maybe_wrap_safe(det: BaseDetector, *, wrap_safe: bool) -> BaseDetector:
    if not wrap_safe:
        return det
    return SafeDetectorWrapper(det)


def get_detector(
    name: str,
    config: Optional[DetectorConfig] = None,
    *,
    wrap_safe: bool = False,
) -> Optional[BaseDetector]:
    """Get detector instance by name.

    Notes:
    - Default returns the raw detector instance (tests rely on this).
    - When wrap_safe=True, returns a SafeDetectorWrapper around the instance.
    """
    detector_class = DETECTOR_REGISTRY.get(name)
    if detector_class is None:
        return None

    instance = detector_class(config=config)
    return _maybe_wrap_safe(instance, wrap_safe=wrap_safe)

