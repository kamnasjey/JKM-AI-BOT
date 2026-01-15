"""
mean_reversion.py
-----------------
Mean-reversion setup detectors.

Detectors:
- MeanReversionSnapbackDetector: Detects deviation from range + snap back entry
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseDetector, DetectorMeta, DetectorResult, SelfTestCase
from .registry import register_detector
from engine_blocks import Candle
from core.primitives import PrimitiveResults


def _range_bounds(candles: List[Candle]) -> tuple:
    """Calculate range high/low from candles.
    
    Returns: (range_high, range_low, range_mid)
    """
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    rh = max(highs)
    rl = min(lows)
    rm = (rh + rl) / 2
    return rh, rl, rm


def _deviation_pct(price: float, bound: float, mid: float) -> float:
    """Calculate % deviation from bound towards mid.
    
    Positive = price has moved beyond bound away from mid.
    """
    half_range = abs(bound - mid)
    if half_range == 0:
        return 0.0
    if bound > mid:  # Upper bound
        deviation = price - bound
    else:  # Lower bound
        deviation = bound - price
    return deviation / half_range


def _is_reversal_candle(bar: Candle, direction: str) -> bool:
    """Check if bar is a reversal candle in given direction.
    
    direction="BUY": bullish reversal (close > open, lower wick)
    direction="SELL": bearish reversal (close < open, upper wick)
    """
    body = abs(bar.close - bar.open)
    full_range = bar.high - bar.low
    
    if full_range == 0:
        return False
    
    body_pct = body / full_range
    
    if direction == "BUY":
        # Bullish: close > open, significant lower wick
        lower_wick = min(bar.open, bar.close) - bar.low
        wick_ratio = lower_wick / full_range if full_range > 0 else 0
        return bar.close > bar.open and wick_ratio > 0.3
    else:
        # Bearish: close < open, significant upper wick
        upper_wick = bar.high - max(bar.open, bar.close)
        wick_ratio = upper_wick / full_range if full_range > 0 else 0
        return bar.close < bar.open and wick_ratio > 0.3


@register_detector
class MeanReversionSnapbackDetector(BaseDetector):
    """Detect deviation from range boundary + snap back entry.
    
    Pattern:
    1. Price deviates beyond established range boundary
    2. Reversal candle forms, snapping back into range
    3. Entry on reversal with SL beyond the deviation point
    """
    
    name = "mean_reversion_snapback"
    meta = DetectorMeta(
        family="mean_reversion",
        supported_regimes=["RANGE"],
        default_score=2.0,
        param_schema={
            "range_lookback": {"type": "int", "default": 20, "min": 10, "max": 50},
            "deviation_threshold": {"type": "float", "default": 0.2, "min": 0.05, "max": 0.5},
            "require_reversal": {"type": "bool", "default": True},
        },
        selftests=[
            SelfTestCase(
                fixture_id="deviation_down_snap_up",
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
        self.range_lookback = int(self.config.get("range_lookback", 20))
        self.deviation_threshold = float(self.config.get("deviation_threshold", 0.2))
        self.require_reversal = bool(self.config.get("require_reversal", True))
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        """Detect deviation + snapback pattern."""
        
        if len(candles) < self.range_lookback + 3:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={"reason": "INSUFFICIENT_DATA"},
                reason_codes=["INSUFFICIENT_DATA"],
                tags=["mean_reversion"],
            )
        
        # Establish range from lookback window (excluding last few bars)
        range_window = candles[-(self.range_lookback + 3):-3]
        range_high, range_low, range_mid = _range_bounds(range_window)
        range_size = range_high - range_low
        
        if range_size <= 0:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={"reason": "NO_RANGE"},
                reason_codes=["NO_RANGE"],
                tags=["mean_reversion"],
            )
        
        # Check recent bars for deviation + snapback
        recent = candles[-3:]
        dev_bar = recent[-2]  # Bar before current (deviation bar)
        snap_bar = recent[-1]  # Current bar (snapback bar)
        
        # Check upper deviation (then expect BUY direction going into range)
        upper_dev = _deviation_pct(dev_bar.high, range_high, range_mid)
        lower_dev = _deviation_pct(dev_bar.low, range_low, range_mid)
        
        direction = None
        deviation_pct = 0.0
        deviation_side = None
        
        if lower_dev > self.deviation_threshold:
            # Deviation below range - potential BUY
            # Snapback = price closes back inside range
            if snap_bar.close > range_low:
                direction = "BUY"
                deviation_pct = lower_dev
                deviation_side = "LOWER"
        elif upper_dev > self.deviation_threshold:
            # Deviation above range - potential SELL
            # Snapback = price closes back inside range
            if snap_bar.close < range_high:
                direction = "SELL"
                deviation_pct = upper_dev
                deviation_side = "UPPER"
        
        if direction is None:
            return DetectorResult(
                detector_name=self.name,
                match=False,
                hit=False,
                direction=None,
                confidence=0.0,
                evidence_dict={
                    "upper_deviation": round(upper_dev, 4),
                    "lower_deviation": round(lower_dev, 4),
                    "threshold": self.deviation_threshold,
                    "reason": "NO_DEVIATION_OR_NO_SNAPBACK",
                },
                reason_codes=["NO_DEVIATION"],
                tags=["mean_reversion"],
            )
        
        # Check for reversal candle if required
        if self.require_reversal:
            is_reversal = _is_reversal_candle(snap_bar, direction)
            if not is_reversal:
                return DetectorResult(
                    detector_name=self.name,
                    match=False,
                    hit=False,
                    direction=None,
                    confidence=0.0,
                    evidence_dict={
                        "deviation_pct": round(deviation_pct, 4),
                        "deviation_side": deviation_side,
                        "reversal_check": False,
                        "reason": "NO_REVERSAL_CANDLE",
                    },
                    reason_codes=["NO_REVERSAL_CANDLE"],
                    tags=["mean_reversion"],
                )
        
        # Calculate entry, SL, TP
        entry = snap_bar.close
        
        if direction == "BUY":
            sl = dev_bar.low - range_size * 0.1  # SL below deviation
            tp = range_mid + (range_mid - range_low) * 0.5  # Target upper mid
        else:
            sl = dev_bar.high + range_size * 0.1  # SL above deviation
            tp = range_mid - (range_high - range_mid) * 0.5  # Target lower mid
        
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 0
        
        confidence = 0.5 + min(deviation_pct, 0.4)  # Cap at 0.9
        
        return DetectorResult(
            detector_name=self.name,
            match=True,
            hit=True,
            direction=direction,
            confidence=round(confidence, 3),
            evidence_dict={
                "range_high": round(range_high, 6),
                "range_low": round(range_low, 6),
                "range_mid": round(range_mid, 6),
                "deviation_pct": round(deviation_pct, 4),
                "deviation_side": deviation_side,
                "deviation_bar_idx": len(candles) - 2,
                "snap_bar_idx": len(candles) - 1,
                "bar_index": len(candles) - 1,
            },
            reason_codes=["MEAN_REVERSION_SNAPBACK", f"DEVIATION_{deviation_side}", f"DIRECTION_{direction}"],
            tags=["mean_reversion", "snapback", deviation_side.lower(), direction.lower()],
            score_contrib=self.meta.default_score,
            entry=round(entry, 6),
            sl=round(sl, 6),
            tp=round(tp, 6),
            rr=round(rr, 2),
        )
