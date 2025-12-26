"""
break_retest.py
---------------
Break and Retest pattern detector.

Detects when price breaks through S/R zone and then retests it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle

from .base import BaseDetector, DetectorSignal


class BreakRetestDetector(BaseDetector):
    """
    Detects break and retest patterns at S/R zones.
    
    Logic:
    1. Identify S/R zones from primitives
    2. Check if price recently broke through zone
    3. Check if price is retesting the zone
    4. Generate signal in direction of break
    """
    
    name = "break_retest"

    doc = (
        "Break & retest around S/R: detects a recent close-through of support/resistance "
        "followed by a retest within tolerance." 
    )
    params_schema = {
        "params.lookback": {"type": "int", "default": 10, "min": 3},
        "params.retest_tolerance": {"type": "float", "default": 0.002, "min": 0.0},
        "min_rr": {"type": "float", "default": 2.0, "min": 0.0},
    }
    examples = [
        {
            "config": {"enabled": True, "params": {"lookback": 10, "retest_tolerance": 0.002}},
            "user_config": {"min_rr": 2.0, "entry_tf": "M15"},
        }
    ]
    
    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        """Detect break & retest setup."""
        
        from core.primitives import PrimitiveResults
        
        if not isinstance(primitives, PrimitiveResults):
            return None
        
        if len(entry_candles) < 20:
            return None
        
        # Get S/R zones from primitives
        sr = primitives.sr_zones
        
        # Get config
        lookback = self.config.params.get("lookback", 10)
        retest_tolerance = self.config.params.get("retest_tolerance", 0.002)  # 0.2%
        min_rr = float(user_config.get("min_rr", 2.0))
        
        # Get recent candles
        recent = entry_candles[-lookback:]
        last_candle = entry_candles[-1]
        
        # Check for resistance break (bullish)
        resistance_broken = False
        for candle in recent[:-1]:
            if candle.close < sr.resistance and last_candle.close > sr.resistance:
                resistance_broken = True
                break
        
        # Check for support break (bearish)
        support_broken = False
        for candle in recent[:-1]:
            if candle.close > sr.support and last_candle.close < sr.support:
                support_broken = True
                break
        
        # Check retest
        if resistance_broken:
            # Bullish breakout, check retest from above
            retest_zone = sr.resistance
            if abs(last_candle.low - retest_zone) / retest_zone <= retest_tolerance:
                # Build BUY signal
                entry = last_candle.close
                sl = sr.support
                risk = entry - sl
                if risk <= 0:
                    return None
                tp = entry + risk * min_rr
                rr = min_rr
                
                return DetectorSignal(
                    detector_name=self.name,
                    pair=pair,
                    direction="BUY",
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    rr=rr,
                    strength=0.6,
                    timeframe=str(user_config.get("entry_tf", "M15")).upper(),
                    reasons=["RESISTANCE_BREAK", "RETEST_OK"],
                    meta={
                        "broken_level": sr.resistance,
                        "retest_zone": retest_zone,
                    },
                )
        
        elif support_broken:
            # Bearish breakout, check retest from below
            retest_zone = sr.support
            if abs(last_candle.high - retest_zone) / retest_zone <= retest_tolerance:
                # Build SELL signal
                entry = last_candle.close
                sl = sr.resistance
                risk = sl - entry
                if risk <= 0:
                    return None
                tp = entry - risk * min_rr
                rr = min_rr
                
                return DetectorSignal(
                    detector_name=self.name,
                    pair=pair,
                    direction="SELL",
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    rr=rr,
                    strength=0.6,
                    timeframe=str(user_config.get("entry_tf", "M15")).upper(),
                    reasons=["SUPPORT_BREAK", "RETEST_OK"],
                    meta={
                        "broken_level": sr.support,
                        "retest_zone": retest_zone,
                    },
                )
        
        return None
