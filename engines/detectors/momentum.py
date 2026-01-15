"""
momentum.py
-----------
Momentum-based setup detectors.

Detectors:
- CompressionExpansionDetector: Detects volatility squeeze followed by expansion
- MomentumContinuationDetector: Detects impulse + pullback + continuation break
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseDetector, DetectorMeta, DetectorResult, SelfTestCase
from .registry import register_detector
from engine_blocks import Candle
from core.primitives import PrimitiveResults


def _range_compression(candles: List[Candle]) -> Tuple[float, float]:
    """Calculate compression ratio.
    
    Returns: (compression_ratio, avg_range)
    Compression = early_range / late_range
    > 1.0 means prices are compressing
    """
    if len(candles) < 6:
        return 0.0, 0.0
    
    mid = len(candles) // 2
    early = candles[:mid]
    late = candles[mid:]
    
    early_ranges = [c.high - c.low for c in early]
    late_ranges = [c.high - c.low for c in late]
    
    avg_early = sum(early_ranges) / len(early_ranges) if early_ranges else 0
    avg_late = sum(late_ranges) / len(late_ranges) if late_ranges else 0
    
    if avg_late == 0:
        return 0.0, (avg_early + avg_late) / 2
    
    return avg_early / avg_late, (avg_early + avg_late) / 2


def _expansion_bar(bar: Candle, avg_range: float, mult: float = 2.0) -> bool:
    """Check if a bar is an expansion bar (range > mult * avg)."""
    return (bar.high - bar.low) > avg_range * mult


def _bar_direction(bar: Candle) -> str:
    """Get bar direction: BUY if bullish, SELL if bearish."""
    return "BUY" if bar.close > bar.open else "SELL"


def _swing_high(candles: List[Candle], idx: int, lookback: int = 2) -> bool:
    """Check if candle at idx is a swing high."""
    if idx < lookback or idx >= len(candles) - lookback:
        return False
    pivot = candles[idx].high
    for i in range(idx - lookback, idx + lookback + 1):
        if i != idx and candles[i].high >= pivot:
            return False
    return True


def _swing_low(candles: List[Candle], idx: int, lookback: int = 2) -> bool:
    """Check if candle at idx is a swing low."""
    if idx < lookback or idx >= len(candles) - lookback:
        return False
    pivot = candles[idx].low
    for i in range(idx - lookback, idx + lookback + 1):
        if i != idx and candles[i].low <= pivot:
            return False
    return True


def _find_recent_swing_high(candles: List[Candle], lookback: int = 15) -> Optional[int]:
    """Find most recent swing high index."""
    for i in range(len(candles) - 3, max(0, len(candles) - lookback - 1), -1):
        if _swing_high(candles, i):
            return i
    return None


def _find_recent_swing_low(candles: List[Candle], lookback: int = 15) -> Optional[int]:
    """Find most recent swing low index."""
    for i in range(len(candles) - 3, max(0, len(candles) - lookback - 1), -1):
        if _swing_low(candles, i):
            return i
    return None


@register_detector
class CompressionExpansionDetector(BaseDetector):
    """Detect volatility compression followed by expansion.
    
    Pattern:
    1. Period of decreasing ranges (compression)
    2. Expansion bar breaking out of compression zone
    """
    
    name = "compression_expansion"
    meta = DetectorMeta(
        family="momentum",
        supported_regimes=["TREND", "RANGE"],
        default_score=2.0,
        param_schema={
            "compression_lookback": {"type": "int", "default": 12, "min": 6, "max": 30},
            "compression_threshold": {"type": "float", "default": 1.3, "min": 1.1, "max": 2.0},
            "expansion_mult": {"type": "float", "default": 1.8, "min": 1.3, "max": 3.0},
        },
        selftests=[
            SelfTestCase(
                fixture_id="squeeze_then_spike_up",
                expect_match=True,
                expect_direction="BUY",
            ),
            SelfTestCase(
                fixture_id="neutral_chop",
                expect_match=False,
                expect_direction=None,
            ),
        ],
        pipeline_stage="setup",
    )
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.compression_lookback = int(self.config.get("compression_lookback", 12))
        self.compression_threshold = float(self.config.get("compression_threshold", 1.3))
        self.expansion_mult = float(self.config.get("expansion_mult", 1.8))
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        """Detect compression + expansion pattern."""
        
        if len(candles) < self.compression_lookback + 2:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={"reason": "INSUFFICIENT_DATA"},
                reason_codes=["INSUFFICIENT_DATA"],
                tags=["momentum"],
            )
        
        # Get compression window (excluding last bar which is the expansion candidate)
        comp_window = candles[-(self.compression_lookback + 1):-1]
        last_bar = candles[-1]
        
        # Calculate compression ratio
        comp_ratio, avg_range = _range_compression(comp_window)
        
        # Check compression
        if comp_ratio < self.compression_threshold:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={
                    "compression_ratio": round(comp_ratio, 4),
                    "threshold": self.compression_threshold,
                    "reason": "NO_COMPRESSION",
                },
                reason_codes=["NO_COMPRESSION"],
                tags=["momentum"],
            )
        
        # Check expansion bar
        is_expansion = _expansion_bar(last_bar, avg_range, self.expansion_mult)
        if not is_expansion:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={
                    "compression_ratio": round(comp_ratio, 4),
                    "expansion_bar": False,
                    "reason": "NO_EXPANSION",
                },
                reason_codes=["COMPRESSION_NO_EXPANSION"],
                tags=["momentum"],
            )
        
        # Pattern detected
        direction = _bar_direction(last_bar)
        confidence = min((comp_ratio / self.compression_threshold) * 0.7, 0.9)
        
        # Calculate entry/sl/tp
        entry = last_bar.close
        if direction == "BUY":
            sl = min(c.low for c in comp_window[-5:])
            risk = entry - sl
            tp = entry + risk * 2.0
        else:
            sl = max(c.high for c in comp_window[-5:])
            risk = sl - entry
            tp = entry - risk * 2.0
        
        rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
        
        return DetectorResult(
            detector_name=self.name,
            match=True,
            hit=True,
            direction=direction,
            confidence=round(confidence, 3),
            evidence_dict={
                "compression_ratio": round(comp_ratio, 4),
                "avg_range": round(avg_range, 6),
                "last_bar_range": round(last_bar.high - last_bar.low, 6),
                "expansion_mult_actual": round((last_bar.high - last_bar.low) / avg_range, 2) if avg_range > 0 else 0,
                "bar_index": len(candles) - 1,
            },
            reason_codes=["COMPRESSION_EXPANSION", f"DIRECTION_{direction}"],
            tags=["momentum", "compression", "expansion", direction.lower()],
            score_contrib=self.meta.default_score,
            entry=round(entry, 6),
            sl=round(sl, 6),
            tp=round(tp, 6),
            rr=round(rr, 2),
        )


@register_detector
class MomentumContinuationDetector(BaseDetector):
    """Detect impulse + pullback + continuation break.
    
    Pattern:
    1. Strong impulse move (directional)
    2. Pullback that doesn't break swing
    3. Continuation candle breaking structure
    """
    
    name = "momentum_continuation"
    meta = DetectorMeta(
        family="momentum",
        supported_regimes=["TREND"],
        default_score=2.5,
        param_schema={
            "impulse_lookback": {"type": "int", "default": 10, "min": 5, "max": 20},
            "impulse_threshold": {"type": "float", "default": 0.3, "min": 0.15, "max": 0.6},
            "pullback_ratio": {"type": "float", "default": 0.5, "min": 0.2, "max": 0.8},
        },
        selftests=[
            SelfTestCase(
                fixture_id="impulse_pullback_break_up",
                expect_match=True,
                expect_direction="BUY",
            ),
            SelfTestCase(
                fixture_id="neutral_chop",
                expect_match=False,
                expect_direction=None,
            ),
        ],
        pipeline_stage="setup",
    )
    
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        self.impulse_lookback = int(self.config.get("impulse_lookback", 10))
        self.impulse_threshold = float(self.config.get("impulse_threshold", 0.3))
        self.pullback_ratio = float(self.config.get("pullback_ratio", 0.5))
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        """Detect impulse + pullback + continuation."""
        
        if len(candles) < self.impulse_lookback + 5:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={"reason": "INSUFFICIENT_DATA"},
                reason_codes=["INSUFFICIENT_DATA"],
                tags=["momentum"],
            )
        
        window = candles[-self.impulse_lookback - 5:]
        last_bar = window[-1]
        
        # Find swing high/low
        swing_high_idx = _find_recent_swing_high(window)
        swing_low_idx = _find_recent_swing_low(window)
        
        if swing_high_idx is None or swing_low_idx is None:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={"reason": "NO_SWING_FOUND"},
                reason_codes=["NO_SWING_STRUCTURE"],
                tags=["momentum"],
            )
        
        swing_high = window[swing_high_idx].high
        swing_low = window[swing_low_idx].low
        swing_range = swing_high - swing_low
        
        if swing_range <= 0:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={"reason": "NO_RANGE"},
                reason_codes=["NO_SWING_RANGE"],
                tags=["momentum"],
            )
        
        # Determine impulse direction based on swing order
        # If swing_low came first, then swing_high, impulse is UP
        is_bullish_impulse = swing_low_idx < swing_high_idx
        
        # Calculate directional ratio
        total_dist = sum(c.high - c.low for c in window[-self.impulse_lookback:])
        directional_ratio = swing_range / total_dist if total_dist > 0 else 0
        
        if directional_ratio < self.impulse_threshold:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={
                    "directional_ratio": round(directional_ratio, 4),
                    "threshold": self.impulse_threshold,
                    "reason": "NO_IMPULSE",
                },
                reason_codes=["NO_IMPULSE"],
                tags=["momentum"],
            )
        
        # Check for pullback
        if is_bullish_impulse:
            # Bullish: after swing_high, price should pull back but stay above swing_low
            pullback_low = min(c.low for c in window[swing_high_idx:])
            pullback_depth = (swing_high - pullback_low) / swing_range
            
            # Check continuation: last bar closes above recent high
            recent_high = max(c.high for c in window[-3:-1])
            is_continuation = last_bar.close > recent_high
            direction = "BUY"
            
            entry = last_bar.close
            sl = pullback_low - swing_range * 0.1
            tp = entry + swing_range
            
        else:
            # Bearish: after swing_low, price should pull back but stay below swing_high
            pullback_high = max(c.high for c in window[swing_low_idx:])
            pullback_depth = (pullback_high - swing_low) / swing_range
            
            # Check continuation: last bar closes below recent low
            recent_low = min(c.low for c in window[-3:-1])
            is_continuation = last_bar.close < recent_low
            direction = "SELL"
            
            entry = last_bar.close
            sl = pullback_high + swing_range * 0.1
            tp = entry - swing_range
        
        # Validate pullback depth
        if pullback_depth > self.pullback_ratio or not is_continuation:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={
                    "pullback_depth": round(pullback_depth, 4),
                    "is_continuation": is_continuation,
                    "reason": "INVALID_PULLBACK_OR_NO_CONTINUATION",
                },
                reason_codes=["NO_CONTINUATION"],
                tags=["momentum"],
            )
        
        rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 0
        confidence = 0.6 + directional_ratio * 0.3
        
        return DetectorResult(
            detector_name=self.name,
            match=True,
            hit=True,
            direction=direction,
            confidence=round(min(confidence, 0.9), 3),
            evidence_dict={
                "directional_ratio": round(directional_ratio, 4),
                "pullback_depth": round(pullback_depth, 4),
                "swing_range": round(swing_range, 6),
                "impulse_direction": "UP" if is_bullish_impulse else "DOWN",
                "bar_index": len(candles) - 1,
            },
            reason_codes=["MOMENTUM_CONTINUATION", f"DIRECTION_{direction}"],
            tags=["momentum", "continuation", direction.lower()],
            score_contrib=self.meta.default_score,
            entry=round(entry, 6),
            sl=round(sl, 6),
            tp=round(tp, 6),
            rr=round(rr, 2),
        )
