"""
pinbar_at_level.py
------------------
Pinbar at key level detector.

Detects pinbar candlestick patterns at Fibonacci or S/R levels.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle, detect_single_candle_patterns

from .base import BaseDetector, DetectorSignal


class PinbarAtLevelDetector(BaseDetector):
    """
    Detects pinbar patterns at key levels (Fibo, S/R).
    
    Logic:
    1. Check last candle for pinbar pattern
    2. Check if pinbar is at/near key level (Fibo retracement or S/R)
    3. Confirm direction aligns with rejection
    4. Generate signal with SL beyond pinbar tail, TP based on RR
    """
    
    name = "pinbar_at_level"

    doc = (
        "Single-candle pinbar (hammer/shooting-star) that rejects a key level (Fibo or S/R) "
        "within a configurable tolerance." 
    )
    params_schema = {
        "params.level_tolerance": {"type": "float", "default": 0.003, "min": 0.0},
        "min_rr": {"type": "float", "default": 2.0, "min": 0.0},
    }
    examples = [
        {
            "config": {"enabled": True, "params": {"level_tolerance": 0.003}},
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
        """Detect pinbar at level setup."""
        
        from core.primitives import PrimitiveResults
        
        if not isinstance(primitives, PrimitiveResults):
            return None
        
        if len(entry_candles) < 5:
            return None
        
        last_candle = entry_candles[-1]
        
        # 1. Check for pinbar pattern
        patterns = detect_single_candle_patterns(last_candle)
        
        # Look for hammer (bullish) or shooting star (bearish)
        is_hammer = any(p.pattern == "hammer" for p in patterns)
        is_shooting_star = any(p.pattern == "shooting_star" for p in patterns)
        
        if not is_hammer and not is_shooting_star:
            return None
        
        # 2. Get key levels from primitives
        fib_levels = primitives.fib_levels
        sr_zones = primitives.sr_zones
        
        # Build list of key levels to check
        key_levels: List[float] = []
        
        # Add Fibo retracement levels
        if fib_levels.retrace:
            key_levels.extend(fib_levels.retrace.values())
        
        # Add S/R levels
        key_levels.append(sr_zones.support)
        key_levels.append(sr_zones.resistance)
        
        # 3. Check if pinbar is at/near any key level
        tolerance = self.config.params.get("level_tolerance", 0.003)  # 0.3%
        min_rr = float(user_config.get("min_rr", 2.0))
        
        at_level = False
        level_price = 0.0
        
        for level in key_levels:
            if level <= 0:
                continue
            # Check if pinbar low or high touches the level
            if abs(last_candle.low - level) / level <= tolerance:
                at_level = True
                level_price = level
                break
            if abs(last_candle.high - level) / level <= tolerance:
                at_level = True
                level_price = level
                break
        
        if not at_level:
            return None
        
        # 4. Generate signal based on pinbar type
        if is_hammer:
            # Bullish pinbar - BUY signal
            entry = last_candle.close
            sl = last_candle.low * 0.999  # Slightly below pinbar tail
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
                strength=0.65,
                timeframe=str(user_config.get("entry_tf", "M15")).upper(),
                reasons=["HAMMER_PINBAR", f"AT_LEVEL_{level_price:.5f}"],
                meta={
                    "pattern": "hammer",
                    "level": level_price,
                    "pinbar_low": last_candle.low,
                },
            )
        
        elif is_shooting_star:
            # Bearish pinbar - SELL signal
            entry = last_candle.close
            sl = last_candle.high * 1.001  # Slightly above pinbar tail
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
                strength=0.65,
                timeframe=str(user_config.get("entry_tf", "M15")).upper(),
                reasons=["SHOOTING_STAR_PINBAR", f"AT_LEVEL_{level_price:.5f}"],
                meta={
                    "pattern": "shooting_star",
                    "level": level_price,
                    "pinbar_high": last_candle.high,
                },
            )
        
        return None
