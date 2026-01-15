"""
pipeline.py
-----------
Optional pipeline mode for detector execution.

Stages:
1. Gates (direction=None, score_contrib=0): informational gates, always run first
2. Setups: produce BUY/SELL candidates
3. Validations: filter/refine candidates (RR feasibility, cooldown, drift)
4. Combine: aggregate scores with correlation discount + confluence bonus

Enable via environment variable: DETECTOR_PIPELINE_MODE=1
Or via config: {"pipeline_mode": true}
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base import BaseDetector, DetectorResult
from .runner import safe_detect
from core.primitives import PrimitiveResults
from engine_blocks import Candle


def is_pipeline_mode_enabled(config: Optional[Dict[str, Any]] = None) -> bool:
    """Check if pipeline mode is enabled."""
    # Check config first
    if config and config.get("pipeline_mode"):
        return True
    # Check environment variable
    env_val = os.getenv("DETECTOR_PIPELINE_MODE", "").strip().lower()
    return env_val in ("1", "true", "yes", "on")


@dataclass
class PipelineStageResult:
    """Result from a pipeline stage."""
    stage_name: str
    results: List[DetectorResult]
    elapsed_ms: float
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Complete pipeline execution result."""
    gate_results: List[DetectorResult]
    setup_results: List[DetectorResult]
    validated_results: List[DetectorResult]
    
    # Aggregated info from gates
    gate_meta: Dict[str, Any] = field(default_factory=dict)
    
    # Recommended skip (based on gates)
    recommended_skip: bool = False
    skip_reason: Optional[str] = None
    
    # Timing
    total_elapsed_ms: float = 0.0
    stage_timings: Dict[str, float] = field(default_factory=dict)


def classify_detector(detector: BaseDetector) -> str:
    """Classify detector into pipeline stage.
    
    Returns: "gate", "setup", or "validation"
    """
    name = getattr(detector, "name", "")
    
    # Gates: detector names starting with "gate_"
    if name.startswith("gate_"):
        return "gate"
    
    # Check meta for explicit classification
    meta = getattr(detector, "meta", None)
    if meta:
        stage = getattr(meta, "pipeline_stage", None)
        if stage in ("gate", "setup", "validation"):
            return stage
    
    # Default: setup
    return "setup"


def run_gates(
    detectors: List[BaseDetector],
    candles: List[Candle],
    primitives: PrimitiveResults,
    context: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Tuple[List[DetectorResult], Dict[str, Any], float]:
    """Run gate detectors and collect informational results.
    
    Returns:
        (results, gate_meta, elapsed_ms)
    """
    t0 = time.perf_counter()
    results: List[DetectorResult] = []
    gate_meta: Dict[str, Any] = {}
    
    for det in detectors:
        if classify_detector(det) != "gate":
            continue
            
        result, _ = safe_detect(
            det,
            candles=candles,
            primitives=primitives,
            context=context,
            **kwargs,
        )
        results.append(result)
        
        # Collect gate meta
        det_name = result.detector_name
        gate_meta[det_name] = {
            "match": result.match,
            "evidence_dict": result.evidence_dict,
            "reason_codes": result.reason_codes,
        }
    
    elapsed = (time.perf_counter() - t0) * 1000.0
    return results, gate_meta, elapsed


def run_setups(
    detectors: List[BaseDetector],
    candles: List[Candle],
    primitives: PrimitiveResults,
    context: Optional[Dict[str, Any]] = None,
    gate_meta: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Tuple[List[DetectorResult], float]:
    """Run setup detectors to produce BUY/SELL candidates.
    
    Returns:
        (results, elapsed_ms)
    """
    t0 = time.perf_counter()
    results: List[DetectorResult] = []
    
    # Enrich context with gate info
    enriched_context = dict(context or {})
    if gate_meta:
        enriched_context["gate_meta"] = gate_meta
    
    for det in detectors:
        if classify_detector(det) != "setup":
            continue
            
        result, _ = safe_detect(
            det,
            candles=candles,
            primitives=primitives,
            context=enriched_context,
            **kwargs,
        )
        
        # Only include hits with direction
        if result.match and result.direction in ("BUY", "SELL"):
            results.append(result)
    
    elapsed = (time.perf_counter() - t0) * 1000.0
    return results, elapsed


def validate_results(
    results: List[DetectorResult],
    primitives: PrimitiveResults,
    config: Optional[Dict[str, Any]] = None,
    gate_meta: Optional[Dict[str, Any]] = None,
    cooldown_state: Optional[Dict[str, Any]] = None,
) -> Tuple[List[DetectorResult], float]:
    """Apply validation filters to setup results.
    
    Validations:
    - RR feasibility check
    - Cooldown / duplicate suppression
    - Drift handling
    
    Returns:
        (validated_results, elapsed_ms)
    """
    t0 = time.perf_counter()
    config = config or {}
    validated: List[DetectorResult] = []
    
    min_rr = float(config.get("min_rr", 1.0))
    cooldown_bars = int(config.get("cooldown_bars", 3))
    drift_reject = bool(config.get("drift_reject", False))
    
    # Cooldown tracking
    cooldown_state = cooldown_state or {}
    
    for result in results:
        det_name = result.detector_name
        
        # V1: RR feasibility check
        if result.rr is not None and result.rr < min_rr:
            # Mark as rejected but don't exclude from results
            result.evidence_dict["validation_rejected"] = True
            result.evidence_dict["rejection_reason"] = "RR_TOO_LOW"
            result.reason_codes = list(result.reason_codes) + ["RR_BELOW_MIN"]
            continue
        
        # V2: Cooldown / duplicate suppression
        last_fire_bar = cooldown_state.get(det_name, -999)
        current_bar = int(result.evidence_dict.get("bar_index", 0))
        if current_bar - last_fire_bar < cooldown_bars:
            result.evidence_dict["validation_rejected"] = True
            result.evidence_dict["rejection_reason"] = "COOLDOWN"
            result.reason_codes = list(result.reason_codes) + ["COOLDOWN_SUPPRESSED"]
            continue
        cooldown_state[det_name] = current_bar
        
        # V3: Drift handling
        if drift_reject and gate_meta:
            drift_gate = gate_meta.get("gate_drift_sentinel", {})
            if drift_gate.get("match") and "DRIFT_ALARM" in drift_gate.get("reason_codes", []):
                result.evidence_dict["validation_rejected"] = True
                result.evidence_dict["rejection_reason"] = "DRIFT_ALARM"
                result.reason_codes = list(result.reason_codes) + ["DRIFT_REJECTED"]
                continue
        
        validated.append(result)
    
    elapsed = (time.perf_counter() - t0) * 1000.0
    return validated, elapsed


def run_pipeline(
    detectors: List[BaseDetector],
    candles: List[Candle],
    primitives: PrimitiveResults,
    context: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    cooldown_state: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> PipelineResult:
    """Execute the full detection pipeline.
    
    Stages:
    1. Gates - informational, always run
    2. Setups - produce BUY/SELL candidates
    3. Validations - filter candidates
    
    Returns:
        PipelineResult with all stage results
    """
    t_total = time.perf_counter()
    config = config or {}
    
    # Stage 1: Gates
    gate_results, gate_meta, gate_ms = run_gates(
        detectors, candles, primitives, context, **kwargs
    )
    
    # Determine if we should recommend skip based on gates
    recommended_skip = False
    skip_reason = None
    
    # Check regime gate
    regime_gate = gate_meta.get("gate_regime", {})
    if regime_gate.get("match"):
        regime = regime_gate.get("evidence_dict", {}).get("regime", "")
        if regime == "CHOP":
            recommended_skip = True
            skip_reason = "REGIME_CHOP"
    
    # Check volatility gate
    vol_gate = gate_meta.get("gate_volatility", {})
    if vol_gate.get("match"):
        reason_codes = vol_gate.get("reason_codes", [])
        if "VOL_INSUFFICIENT_BARS" in reason_codes:
            recommended_skip = True
            skip_reason = "INSUFFICIENT_VOLATILITY_DATA"
    
    # Stage 2: Setups
    setup_results, setup_ms = run_setups(
        detectors, candles, primitives, context, gate_meta, **kwargs
    )
    
    # Stage 3: Validations
    validated_results, validate_ms = validate_results(
        setup_results, primitives, config, gate_meta, cooldown_state
    )
    
    total_ms = (time.perf_counter() - t_total) * 1000.0
    
    return PipelineResult(
        gate_results=gate_results,
        setup_results=setup_results,
        validated_results=validated_results,
        gate_meta=gate_meta,
        recommended_skip=recommended_skip,
        skip_reason=skip_reason,
        total_elapsed_ms=total_ms,
        stage_timings={
            "gates": gate_ms,
            "setups": setup_ms,
            "validations": validate_ms,
        },
    )
