"""
base.py
-------
Base detector interface and result types for plugin architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Set

from engine_blocks import Candle
from core.primitives import PrimitiveResults
from core.types import Regime



@dataclass(frozen=True)
class SelfTestCase:
    """Deterministic detector self-test case.

    These are used by the QA gate to ensure each detector can produce
    at least one HIT and one NO_HIT on stable fixtures.
    """

    fixture_id: str
    expect_match: bool
    expect_direction: Optional[Literal["BUY", "SELL"]] = None
    config_overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectorMeta:
    family: str = "misc"  # sr/structure/range/pattern/fibo/geometry/time/...
    supported_regimes: Set[str] = field(
        default_factory=lambda: {
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        }
    )
    default_score: float = 1.0

    # Optional schema describing supported detector parameters.
    # Used for deterministic, schema-based diagnosis (no heuristics).
    # Shape (example):
    # {
    #   "touch_tolerance": {"type": "float", "min": 0.0001, "max": 0.01, "strict_low": 0.0005, "default": 0.001}
    # }
    param_schema: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Optional deterministic self-tests.
    selftests: List[SelfTestCase] = field(default_factory=list)

    # Pipeline stage: "gate", "setup", or "validation".
    # Gates run first (informational), setups produce signals, validations filter.
    pipeline_stage: str = "setup"


@dataclass
class DetectorResult:
    """
    Standardized result from any detector.
    
    This is the universal format that all detectors must return.
    """
    
    detector_name: str
    match: bool  # True if pattern/condition detected
    direction: Optional[Literal["BUY", "SELL"]] = None
    confidence: float = 0.5  # 0.0 to 1.0

    # Stable, user-facing setup identifier (required by QA gate).
    # Defaults to detector_name to keep existing detectors working.
    setup_name: str = ""
    
    # Evidence/reasons for the detection
    evidence: List[str] = field(default_factory=list)

    # Soft-combine fields (v1)
    # - reasons: human-readable reason strings (defaults to `evidence`)
    # - evidence_dict: JSON-serializable evidence payload (defaults to `meta`)
    # - tags: detector family tags for confluence bonus
    # - score_contrib: contribution to aggregate score (defaults to `confidence`)
    reasons: List[str] = field(default_factory=list)
    evidence_dict: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    score_contrib: Optional[float] = None
    
    # Optional trade setup (if detector can provide it)
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    rr: Optional[float] = None
    
    # Additional metadata
    meta: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[datetime] = None

    # --- Future-proof contract fields (schema v2) ---
    # `hit` is the canonical boolean; `match` remains supported for backward compatibility.
    hit: bool = False

    # Stable, machine-readable reason codes (not free-form sentences).
    # Existing detectors may leave this empty.
    reason_codes: List[str] = field(default_factory=list)

    # Schema version for this result contract.
    schema_version: int = 0

    def __post_init__(self) -> None:
        # Default schema version.
        if not self.schema_version:
            try:
                from core.version import DETECTOR_RESULT_SCHEMA_VERSION

                self.schema_version = int(DETECTOR_RESULT_SCHEMA_VERSION)
            except Exception:
                self.schema_version = 2

        if not self.setup_name:
            self.setup_name = self.detector_name
        if not self.reasons and self.evidence:
            self.reasons = list(self.evidence)
        if not self.evidence_dict and self.meta:
            # Best-effort: ensure JSON-serializable values only.
            # Keep raw meta if it already is serializable.
            self.evidence_dict = dict(self.meta)
        if self.score_contrib is None:
            self.score_contrib = float(self.confidence)

        # Canonicalize hit/match.
        try:
            self.hit = bool(self.match)
        except Exception:
            self.hit = False
            self.match = False

        # Reason codes: normalize to non-empty strings.
        try:
            if not isinstance(self.reason_codes, list):
                self.reason_codes = []
            self.reason_codes = [str(x).strip() for x in self.reason_codes if str(x).strip()]
        except Exception:
            self.reason_codes = []

    @property
    def evidence_payload(self) -> Dict[str, Any]:
        """Canonical evidence payload (dict).

        Note: `evidence` is a legacy list[str] field, so we expose the dict via
        `evidence_payload` to avoid breaking dataclass field semantics.
        """
        try:
            return dict(self.evidence_dict or {})
        except Exception:
            return {}


class BaseDetector(ABC):
    """
    Base class for all detector plugins.
    
    Each detector implements a specific pattern or condition detection.
    Detectors are stateless and work purely on input data + primitives.
    """
    
    # Must be overridden by subclasses
    name: str = "base_detector"
    description: str = "Base detector"

    # Regime support + scoring family (legacy, still supported)
    supported_regimes: Set[str] = {
        Regime.TREND_BULL.value,
        Regime.TREND_BEAR.value,
        Regime.RANGE.value,
        Regime.CHOP.value,
    }
    family: str = "misc"

    # New metadata container (preferred going forward)
    meta: DetectorMeta = DetectorMeta()
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize detector with optional configuration.
        
        Args:
            config: Detector-specific configuration parameters
        """
        self.config = config or {}
        self.enabled = self.config.get("enabled", True)

        # Instance-level meta (avoid mutating shared class defaults).
        try:
            cls = self.__class__
            cls_dict = getattr(cls, "__dict__", {}) or {}

            # IMPORTANT:
            # - Inherited attributes (from BaseDetector) are always present via getattr().
            # - For correct precedence we must distinguish explicit overrides
            #   (present in cls.__dict__) vs inherited defaults.
            explicit_meta = "meta" in cls_dict
            explicit_family = "family" in cls_dict
            explicit_supported = "supported_regimes" in cls_dict

            meta_obj = cls_dict.get("meta") if explicit_meta else None
            family_obj = cls_dict.get("family") if explicit_family else None
            supported_obj = cls_dict.get("supported_regimes") if explicit_supported else None

            # Precedence:
            # 1) explicit `meta = DetectorMeta(...)` on subclass
            # 2) explicit legacy `family` / `supported_regimes` on subclass
            # 3) inherited defaults
            if meta_obj is not None:
                fam = str(getattr(meta_obj, "family", "") or "misc")
                sr = getattr(meta_obj, "supported_regimes", None)
                ds = float(getattr(meta_obj, "default_score", 1.0) or 1.0)
                ps = getattr(meta_obj, "param_schema", None)
                st = getattr(meta_obj, "selftests", None)
            else:
                fam = str(family_obj) if family_obj is not None else str(getattr(cls, "family", "misc") or "misc")
                sr = supported_obj if supported_obj is not None else getattr(cls, "supported_regimes", None)
                ds = 1.0
                ps = None
                st = None

            sr_set = set(sr or [])
            if not sr_set:
                sr_set = {
                    Regime.TREND_BULL.value,
                    Regime.TREND_BEAR.value,
                    Regime.RANGE.value,
                    Regime.CHOP.value,
                }

            param_schema: Dict[str, Dict[str, Any]] = {}
            if isinstance(ps, dict):
                # Shallow copy to avoid accidental shared mutation.
                param_schema = {str(k): (dict(v) if isinstance(v, dict) else {}) for k, v in ps.items()}

            selftests: List[SelfTestCase] = []
            if isinstance(st, list):
                # Best-effort shallow copy (cases are frozen dataclasses).
                selftests = [x for x in st if isinstance(x, SelfTestCase)]

            self.meta = DetectorMeta(
                family=fam,
                supported_regimes=sr_set,
                default_score=ds,
                param_schema=param_schema,
                selftests=selftests,
            )
        except Exception:
            self.meta = DetectorMeta()
    
    @abstractmethod
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        """
        Main detection method - must be implemented by subclasses.
        
        Args:
            candles: List of candles (entry timeframe)
            primitives: Pre-computed primitive results
            context: Optional context (pair name, timeframe, user config, etc.)
            
        Returns:
            DetectorResult with match status and details
        """
        pass
    
    def is_enabled(self) -> bool:
        """Check if detector is enabled."""
        return self.enabled
    
    def get_name(self) -> str:
        """Get detector name."""
        return self.name
    
    def get_description(self) -> str:
        """Get detector description."""
        return self.description

    def supports_regime(self, regime: str) -> bool:
        try:
            # Prefer meta.supported_regimes when available.
            if hasattr(self, "meta") and getattr(self, "meta") is not None:
                return str(regime) in set(getattr(self.meta, "supported_regimes", set()) or set())

            sr = getattr(self, "supported_regimes", None)
            if sr is None:
                return True
            if isinstance(sr, set):
                return str(regime) in sr
            return str(regime) in set(sr or [])
        except Exception:
            return True

    def get_family(self) -> str:
        try:
            if hasattr(self, "meta") and getattr(self, "meta") is not None:
                return str(getattr(self.meta, "family", "misc") or "misc")
        except Exception:
            pass
        return str(getattr(self, "family", "misc") or "misc")


class DetectorGroup:
    """
    Group of related detectors that can be run together.
    
    Example: All S/R detectors, all candlestick pattern detectors, etc.
    """
    
    def __init__(self, name: str, detectors: List[BaseDetector]):
        self.name = name
        self.detectors = detectors
    
    def run_all(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[DetectorResult]:
        """
        Run all detectors in the group.
        
        Returns:
            List of DetectorResult from all enabled detectors
        """
        results = []
        for detector in self.detectors:
            if detector.is_enabled():
                try:
                    result = detector.detect(candles, primitives, context)
                    if result.match:
                        results.append(result)
                except Exception as e:
                    # Log error but don't fail entire group
                    print(f"Error in detector {detector.name}: {e}")
        
        return results
