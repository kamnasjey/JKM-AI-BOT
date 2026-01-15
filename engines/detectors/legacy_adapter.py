"""
legacy_adapter.py
-----------------
Adapter to wrap legacy detectors (detectors/) for the new engine system (engines/detectors/).

This allows the 15 existing detectors to work seamlessly with the new
unified registry and pipeline architecture.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from .base import BaseDetector as NewBaseDetector, DetectorResult, DetectorMeta
from .registry import register_detector

# Import legacy detector system
from detectors.base import BaseDetector as LegacyBaseDetector, DetectorSignal, DetectorConfig
from detectors.registry import DETECTOR_REGISTRY as LEGACY_REGISTRY

from engine_blocks import Candle
from core.primitives import PrimitiveResults

# Skip duplicates - these exist in engines/detectors with better implementations
DUPLICATES_TO_SKIP = {
    "pinbar_at_level",      # engines/detectors/candles.py has improved version
    "fibo_retrace_confluence",  # engines/detectors/fibo.py
    "sr_role_reversal",     # engines/detectors/sr.py
    "fakeout_trap",         # engines/detectors/range.py
}


class LegacyDetectorAdapter(NewBaseDetector):
    """
    Adapter that wraps a legacy detector to work with the new system.
    
    Converts:
    - New detect(candles, primitives, context) -> Legacy detect(pair, entry_candles, trend_candles, primitives, user_config)
    - DetectorSignal -> DetectorResult
    """
    
    def __init__(
        self,
        legacy_class: Type[LegacyBaseDetector],
        config: Optional[Dict[str, Any]] = None,
    ):
        # Initialize new base
        super().__init__(config)
        
        # Create legacy detector instance
        legacy_config = DetectorConfig(
            enabled=config.get("enabled", True) if config else True,
            params=config.get("params", {}) if config else {},
        )
        self.legacy_detector = legacy_class(config=legacy_config)
        
        # Copy metadata from legacy
        self.name = self.legacy_detector.name
        self.description = getattr(self.legacy_detector, "doc", "") or ""
        
        # Build meta from legacy attributes
        self.meta = DetectorMeta(
            family=self._infer_family(self.name),
            default_score=1.0,
            param_schema=getattr(self.legacy_detector, "params_schema", {}),
            pipeline_stage="setup",  # Legacy detectors are all setup/trigger type
        )
    
    def _infer_family(self, name: str) -> str:
        """Infer detector family from name."""
        if "fibo" in name:
            return "fibo"
        if "sr" in name or "break" in name or "retest" in name:
            return "sr"
        if "pinbar" in name or "engulf" in name:
            return "candles"
        if "head" in name or "double" in name or "triangle" in name or "flag" in name or "rectangle" in name:
            return "pattern"
        if "momentum" in name:
            return "momentum"
        return "misc"
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        """
        Run legacy detector and convert result to new format.
        """
        ctx = context or {}
        pair = ctx.get("pair", ctx.get("symbol", "UNKNOWN"))
        user_config = ctx.get("user_config", {})
        
        # Legacy needs both entry and trend candles
        # For now, use same candles (caller should provide trend in context if needed)
        entry_candles = candles
        trend_candles = ctx.get("trend_candles", candles)
        
        try:
            signal: Optional[DetectorSignal] = self.legacy_detector.detect(
                pair=pair,
                entry_candles=entry_candles,
                trend_candles=trend_candles,
                primitives=primitives,
                user_config=user_config,
            )
        except Exception as e:
            # Return no-match on error
            return DetectorResult(
                detector_name=self.name,
                match=False,
                evidence=[f"Error: {e}"],
            )
        
        if signal is None:
            return DetectorResult(
                detector_name=self.name,
                match=False,
            )
        
        # Convert DetectorSignal to DetectorResult
        return DetectorResult(
            detector_name=self.name,
            match=True,
            direction=signal.direction,
            confidence=signal.strength,
            evidence=signal.reasons,
            entry=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
            rr=signal.rr,
            tags=[self.meta.family],
            meta=signal.meta,
        )
    
    def get_doc(self) -> str:
        return getattr(self.legacy_detector, "doc", self.description)
    
    def get_params_schema(self) -> Dict[str, Any]:
        return getattr(self.legacy_detector, "params_schema", {})
    
    def get_examples(self) -> List[Dict[str, Any]]:
        return getattr(self.legacy_detector, "examples", [])


def create_legacy_adapter(name: str) -> Type[NewBaseDetector]:
    """
    Factory to create an adapter class for a legacy detector.
    
    This creates a proper class (not instance) that can be registered
    with @register_detector or added to the registry.
    """
    legacy_class = LEGACY_REGISTRY.get(name)
    if legacy_class is None:
        raise ValueError(f"Legacy detector not found: {name}")
    
    # Create a new class dynamically
    class_name = f"{legacy_class.__name__}Adapted"
    
    def init_method(self, config: Optional[Dict[str, Any]] = None):
        LegacyDetectorAdapter.__init__(self, legacy_class, config)
    
    AdaptedClass = type(
        class_name,
        (LegacyDetectorAdapter,),
        {
            "__init__": init_method,
            "name": legacy_class.name if hasattr(legacy_class, "name") else name,
        },
    )
    
    return AdaptedClass


def register_all_legacy_detectors() -> int:
    """
    Register all legacy detectors with the new unified registry.

    Notes:
    - Skips detectors that have preferred implementations in engines/detectors/.
    - Never overrides detectors that are already registered (import-order safe).
    
    Returns:
        Number of detectors registered
    """
    from .registry import detector_registry
    
    count = 0
    for name, legacy_class in LEGACY_REGISTRY.items():
        # Prefer engines/detectors implementations for duplicates.
        if name in DUPLICATES_TO_SKIP:
            continue

        # Never override an already-registered detector.
        if name in getattr(detector_registry, "_detectors", {}):
            continue

        try:
            # Create adapter class
            AdaptedClass = create_legacy_adapter(name)
            
            # Register with new registry
            detector_registry.register(AdaptedClass)
            count += 1
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to adapt legacy detector {name}: {e}")
    
    return count


# Auto-register on import
_LEGACY_REGISTERED = False

def ensure_legacy_registered():
    """Ensure legacy detectors are registered (idempotent)."""
    global _LEGACY_REGISTERED
    if _LEGACY_REGISTERED:
        return
    
    try:
        register_all_legacy_detectors()
        _LEGACY_REGISTERED = True
    except Exception:
        pass
