"""
gates.py
--------
Gate detectors for pipeline mode.

Gates produce direction=None, score_contrib=0.
They provide informational context for downstream detectors.

Detectors:
- RegimeGateDetector: Trend vs Range vs Chop classification
- VolatilityGateDetector: Volatility state (high/low/insufficient)
- DriftSentinelDetector: Detects drift / data anomalies
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import BaseDetector, DetectorMeta, DetectorResult, SelfTestCase
from .registry import register_detector
from engine_blocks import Candle
from core.primitives import PrimitiveResults


def _body_range(candles: List[Candle]) -> float:
    """Calculate avg body range as % of avg candle height."""
    if not candles:
        return 0.0
    bodies = []
    for c in candles:
        h = c.high - c.low
        b = abs(c.close - c.open)
        if h > 0:
            bodies.append(b / h)
    return sum(bodies) / len(bodies) if bodies else 0.0


def _directional_ratio(candles: List[Candle]) -> float:
    """Ratio of price movement to distance traveled."""
    if len(candles) < 2:
        return 0.0
    net_move = abs(candles[-1].close - candles[0].open)
    total_dist = sum(c.high - c.low for c in candles)
    if total_dist == 0:
        return 0.0
    return net_move / total_dist


def _atr_like(candles: List[Candle]) -> float:
    """Simple ATR approximation without dependencies."""
    if len(candles) < 2:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        prev_c = candles[i - 1].close
        h = candles[i].high
        l = candles[i].low
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


@register_detector
class RegimeGateDetector(BaseDetector):
    """Classify market regime: TREND_UP, TREND_DOWN, RANGE, CHOP."""
    
    name = "gate_regime"
    meta = DetectorMeta(
        family="gate",
        supported_regimes=["TREND", "RANGE", "CHOP"],  # all
        default_score=0.0,  # gates don't contribute score
        param_schema={
            "lookback": {"type": "int", "default": 20, "min": 5, "max": 100},
            "trend_threshold": {"type": "float", "default": 0.4, "min": 0.1, "max": 0.9},
            "chop_threshold": {"type": "float", "default": 0.2, "min": 0.05, "max": 0.5},
        },
        selftests=[
            SelfTestCase(
                fixture_id="structure_up",
                expect_match=True,
                expect_direction=None,  # gates always None
            ),
            SelfTestCase(
                fixture_id="range_mid_nohit",
                expect_match=True,
                expect_direction=None,
            ),
        ],
        pipeline_stage="gate",
    )
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.lookback = int(self.config.get("lookback", 20))
        self.trend_threshold = float(self.config.get("trend_threshold", 0.4))
        self.chop_threshold = float(self.config.get("chop_threshold", 0.2))
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        """Classify regime based on directional ratio and body patterns."""
        
        if len(candles) < max(5, self.lookback):
            return DetectorResult(
                detector_name=self.name,
                match=True,
                hit=False,
                direction=None,  # Gates always None
                confidence=0.0,
                evidence_dict={
                    "regime": "UNKNOWN",
                    "reason": "INSUFFICIENT_DATA",
                    "bars_available": len(candles),
                    "bars_required": self.lookback,
                },
                reason_codes=["REGIME_UNKNOWN", "INSUFFICIENT_DATA"],
                tags=["gate", "regime"],
                score_contrib=0.0,
            )
        
        window = candles[-self.lookback:]
        dr = _directional_ratio(window)
        br = _body_range(window)
        
        # Determine price direction
        net_change = window[-1].close - window[0].open
        is_up = net_change > 0
        
        # Classify regime
        if dr >= self.trend_threshold:
            regime = "TREND_UP" if is_up else "TREND_DOWN"
            reason_codes = ["REGIME_TREND_UP"] if is_up else ["REGIME_TREND_DOWN"]
        elif dr <= self.chop_threshold:
            # Low directional ratio + small bodies = chop
            if br < 0.5:
                regime = "CHOP"
                reason_codes = ["REGIME_CHOP"]
            else:
                regime = "RANGE"
                reason_codes = ["REGIME_RANGE"]
        else:
            regime = "RANGE"
            reason_codes = ["REGIME_RANGE"]
        
        return DetectorResult(
            detector_name=self.name,
            match=True,
            hit=False,  # Gates don't produce "hits"
            direction=None,  # Gates always None
            confidence=min(dr / self.trend_threshold, 1.0) if dr >= self.chop_threshold else 0.5,
            evidence_dict={
                "regime": regime,
                "directional_ratio": round(dr, 4),
                "body_range_pct": round(br, 4),
                "net_change": round(net_change, 6),
                "lookback": self.lookback,
                "bar_index": len(candles) - 1,
            },
            reason_codes=reason_codes,
            tags=["gate", "regime", regime.lower()],
            score_contrib=0.0,
        )


@register_detector
class VolatilityGateDetector(BaseDetector):
    """Classify volatility state: HIGH, LOW, NORMAL, INSUFFICIENT_BARS."""
    
    name = "gate_volatility"
    meta = DetectorMeta(
        family="gate",
        supported_regimes=["TREND", "RANGE", "CHOP"],
        default_score=0.0,
        param_schema={
            "lookback": {"type": "int", "default": 20, "min": 5, "max": 100},
            "high_mult": {"type": "float", "default": 1.5, "min": 1.1, "max": 3.0},
            "low_mult": {"type": "float", "default": 0.5, "min": 0.1, "max": 0.9},
        },
        selftests=[
            SelfTestCase(
                fixture_id="smoke",
                expect_match=True,
                expect_direction=None,
            ),
        ],
        pipeline_stage="gate",
    )
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.lookback = int(self.config.get("lookback", 20))
        self.high_mult = float(self.config.get("high_mult", 1.5))
        self.low_mult = float(self.config.get("low_mult", 0.5))
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        """Classify volatility based on recent vs historical ATR."""
        
        min_bars = self.lookback + 10
        if len(candles) < min_bars:
            return DetectorResult(
                detector_name=self.name,
                match=True,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={
                    "vol_state": "INSUFFICIENT_BARS",
                    "bars_available": len(candles),
                    "bars_required": min_bars,
                    "bar_index": len(candles) - 1,
                },
                reason_codes=["VOL_INSUFFICIENT_BARS"],
                tags=["gate", "volatility"],
                score_contrib=0.0,
            )
        
        # Recent ATR (last 5 bars)
        recent_atr = _atr_like(candles[-5:])
        # Historical ATR (lookback window)
        hist_atr = _atr_like(candles[-self.lookback:])
        
        if hist_atr == 0:
            vol_ratio = 1.0
        else:
            vol_ratio = recent_atr / hist_atr
        
        # Classify
        if vol_ratio >= self.high_mult:
            vol_state = "HIGH"
            reason_codes = ["VOL_HIGH"]
        elif vol_ratio <= self.low_mult:
            vol_state = "LOW"
            reason_codes = ["VOL_LOW"]
        else:
            vol_state = "NORMAL"
            reason_codes = ["VOL_NORMAL"]
        
        return DetectorResult(
            detector_name=self.name,
            match=True,
            hit=False,
            direction=None,
            confidence=0.7,
            evidence_dict={
                "vol_state": vol_state,
                "vol_ratio": round(vol_ratio, 4),
                "recent_atr": round(recent_atr, 6),
                "hist_atr": round(hist_atr, 6),
                "lookback": self.lookback,
                "bar_index": len(candles) - 1,
            },
            reason_codes=reason_codes,
            tags=["gate", "volatility", vol_state.lower()],
            score_contrib=0.0,
        )


@register_detector
class DriftSentinelDetector(BaseDetector):
    """Detect data drift / anomalies that might affect signal quality."""
    
    name = "gate_drift_sentinel"
    meta = DetectorMeta(
        family="gate",
        supported_regimes=["TREND", "RANGE", "CHOP"],
        default_score=0.0,
        param_schema={
            "gap_pct_threshold": {"type": "float", "default": 0.02, "min": 0.005, "max": 0.1},
            "spike_mult": {"type": "float", "default": 3.0, "min": 2.0, "max": 10.0},
        },
        selftests=[
            SelfTestCase(
                fixture_id="smoke",
                expect_match=True,
                expect_direction=None,
            ),
        ],
        pipeline_stage="gate",
    )
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.gap_pct_threshold = float(self.config.get("gap_pct_threshold", 0.02))
        self.spike_mult = float(self.config.get("spike_mult", 3.0))
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        """Check for gaps and spikes that indicate potential data issues."""
        
        if len(candles) < 10:
            return DetectorResult(
                detector_name=self.name,
                match=True,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={
                    "drift_detected": False,
                    "reason": "INSUFFICIENT_DATA",
                    "bar_index": len(candles) - 1,
                },
                reason_codes=["DRIFT_INSUFFICIENT_DATA"],
                tags=["gate", "drift"],
                score_contrib=0.0,
            )
        
        alarms: List[str] = []
        evidence: Dict[str, Any] = {
            "drift_detected": False,
            "bar_index": len(candles) - 1,
        }
        
        # Check for gap
        if len(candles) >= 2:
            prev_close = candles[-2].close
            curr_open = candles[-1].open
            gap_pct = abs(curr_open - prev_close) / prev_close if prev_close else 0
            if gap_pct > self.gap_pct_threshold:
                alarms.append("GAP_DETECTED")
                evidence["gap_pct"] = round(gap_pct, 6)
        
        # Check for volume spike (if available) or range spike
        recent_ranges = [c.high - c.low for c in candles[-20:-1]]
        if recent_ranges:
            avg_range = sum(recent_ranges) / len(recent_ranges)
            last_range = candles[-1].high - candles[-1].low
            if avg_range > 0 and last_range > avg_range * self.spike_mult:
                alarms.append("RANGE_SPIKE")
                evidence["range_spike_mult"] = round(last_range / avg_range, 2)
        
        # Check for stale data (identical bars)
        if len(candles) >= 3:
            last_3 = candles[-3:]
            if all(c.open == c.high == c.low == c.close for c in last_3):
                alarms.append("STALE_DATA")
        
        drift_detected = len(alarms) > 0
        evidence["drift_detected"] = drift_detected
        evidence["alarms"] = alarms
        
        reason_codes = ["DRIFT_ALARM"] if drift_detected else ["DRIFT_CLEAR"]
        reason_codes.extend(alarms)
        
        return DetectorResult(
            detector_name=self.name,
            match=True,
            hit=False,
            direction=None,
            confidence=0.8 if drift_detected else 0.9,
            evidence_dict=evidence,
            reason_codes=reason_codes,
            tags=["gate", "drift"] + (["alarm"] if drift_detected else ["clear"]),
            score_contrib=0.0,
        )
