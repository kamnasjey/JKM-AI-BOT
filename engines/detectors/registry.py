"""
registry.py
-----------
Detector registry and loader for plugin architecture.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from .base import BaseDetector, DetectorResult
from engine_blocks import Candle
from core.primitives import PrimitiveResults


class DetectorRegistry:
    """
    Central registry for all detector plugins.
    
    Manages loading, enabling/disabling, and running detectors based on
    user profile configuration.
    """
    
    def __init__(self):
        self._detectors: Dict[str, Type[BaseDetector]] = {}
    
    def register(self, detector_class: Type[BaseDetector]) -> None:
        """
        Register a detector class.
        
        Args:
            detector_class: Detector class (subclass of BaseDetector)
        """
        name = detector_class.name
        self._detectors[name] = detector_class
    
    def get_detector_class(self, name: str) -> Optional[Type[BaseDetector]]:
        """Get detector class by name."""
        return self._detectors.get(name)
    
    def list_detectors(self) -> List[str]:
        """List all registered detector names."""
        return list(self._detectors.keys())

    def count(self) -> int:
        """Return number of registered detectors."""
        return int(len(self._detectors))
    
    def create_detector(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None,
        *,
        flags: Optional[Any] = None,
    ) -> Optional[BaseDetector]:
        """
        Create an instance of a detector.
        
        Args:
            name: Detector name
            config: Configuration for the detector
            
        Returns:
            Detector instance or None if not found
        """
        detector_class = self._detectors.get(name)
        if detector_class is None:
            return None
        
        det = detector_class(config=config)

        # Feature-flag gate (default safe: OFF unless explicitly enabled).
        try:
            ff = getattr(detector_class, "feature_flag", None)
            if ff:
                from core.feature_flags import FeatureFlags

                fl = flags if isinstance(flags, FeatureFlags) else FeatureFlags.from_sources(config=None)
                if not fl.is_enabled(str(ff)):
                    return None
        except Exception:
            # If gating fails, be conservative: disable.
            return None

        return det
    
    def load_from_profile(
        self,
        profile: Dict[str, Any],
        default_detectors: Optional[List[str]] = None,
        *,
        flags: Optional[Any] = None,
    ) -> List[BaseDetector]:
        """
        Load and instantiate detectors based on user profile.
        
        Profile format:
        {
            "detectors": {
                "sr_bounce": {"enabled": true, "params": {...}},
                "pinbar": {"enabled": true},
                ...
            }
        }
        
        Args:
            profile: User profile dict
            default_detectors: List of detector names to enable by default if no config
            
        Returns:
            List of enabled detector instances
        """
        detector_configs = profile.get("detectors", {})

        # Resolve flags once.
        try:
            from core.feature_flags import FeatureFlags

            ff_cfg = profile.get("feature_flags")
            fl = flags if isinstance(flags, FeatureFlags) else FeatureFlags.from_sources(config=ff_cfg)
        except Exception:
            fl = None
        
        # If no detector config, use defaults
        if not detector_configs and default_detectors:
            out: List[BaseDetector] = []
            for name in default_detectors:
                if self.get_detector_class(name) is None:
                    continue
                det = self.create_detector(name, {"enabled": True}, flags=fl)
                if det is not None:
                    out.append(det)
            return out
        
        # Load configured detectors
        detectors = []
        for name, config in detector_configs.items():
            if not isinstance(config, dict):
                continue
            
            # Check if enabled
            if not config.get("enabled", False):
                continue
            
            # Create detector instance
            detector = self.create_detector(name, config, flags=fl)
            if detector:
                detectors.append(detector)
        
        return detectors
    
    def run_all(
        self,
        detectors: List[BaseDetector],
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[DetectorResult]:
        """
        Run all detectors and collect results.
        
        Args:
            detectors: List of detector instances
            candles: Candle data
            primitives: Pre-computed primitives
            context: Optional context
            
        Returns:
            List of DetectorResult (only matches)
        """
        results = []
        
        for detector in detectors:
            if not detector.is_enabled():
                continue
            
            from .runner import safe_detect

            result, _ms = safe_detect(
                detector,
                candles=candles,
                primitives=primitives,
                context=context,
            )
            if result.match:
                results.append(result)
        
        return results


# Global singleton instance
detector_registry = DetectorRegistry()

_REGISTRY_LOADED: bool = False


def ensure_registry_loaded(*, logger: Any = None, custom_dir: str = "detectors/custom") -> None:
    """Ensure built-in (and optional custom) detectors are imported at least once.

    This is intentionally best-effort and non-fatal by default.
    """
    global _REGISTRY_LOADED
    if _REGISTRY_LOADED:
        return

    # 1) Built-in packs: importing the package triggers module imports and decorator registration.
    try:
        import engines.detectors  # noqa: F401
    except Exception as e:
        try:
            from metrics.plugin_events import emit_plugin_event_now

            emit_plugin_event_now(
                event="REGISTRY_LOAD_ISSUE",
                scan_id="NA",
                detector="engines.detectors",
                message=f"{type(e).__name__}:{e}",
            )
        except Exception:
            pass
        if logger is not None:
            try:
                from engine.utils.logging_utils import log_kv_warning

                log_kv_warning(logger, "REGISTRY_LOAD_ISSUE", err=f"{type(e).__name__}:{e}")
            except Exception:
                pass

    # 2) Custom detectors: optional.
    try:
        if custom_dir:
            if logger is not None:
                from detectors.custom_loader import load_custom_detectors_with_logs
                from engine.utils.logging_utils import log_kv, log_kv_warning

                load_custom_detectors_with_logs(
                    logger,
                    custom_dir=str(custom_dir),
                    log_kv=log_kv,
                    log_kv_warning=log_kv_warning,
                )
            else:
                from detectors.custom_loader import load_custom_detectors

                load_custom_detectors(str(custom_dir))
    except Exception as e:
        try:
            from metrics.plugin_events import emit_plugin_event_now

            emit_plugin_event_now(
                event="REGISTRY_LOAD_ISSUE",
                scan_id="NA",
                detector="custom_detectors",
                message=f"{type(e).__name__}:{e}",
                extra={"custom_dir": str(custom_dir)},
            )
        except Exception:
            pass
        if logger is not None:
            try:
                from engine.utils.logging_utils import log_kv_warning

                log_kv_warning(logger, "REGISTRY_LOAD_ISSUE", custom_dir=str(custom_dir), err=f"{type(e).__name__}:{e}")
            except Exception:
                pass

    _REGISTRY_LOADED = True


def register_detector(detector_class: Type[BaseDetector]):
    """
    Decorator to register a detector class.
    
    Usage:
        @register_detector
        class MyDetector(BaseDetector):
            name = "my_detector"
            ...
    """
    detector_registry.register(detector_class)
    return detector_class
