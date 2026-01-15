"""
candles.py
----------
Candlestick pattern detector plugins.
"""

from typing import Any, Dict, List, Optional

from .base import BaseDetector, DetectorMeta, DetectorResult, SelfTestCase
from .registry import register_detector
from engine_blocks import Candle, detect_single_candle_patterns
from core.primitives import PrimitiveResults
from core.types import Regime


# MERGED: use pinbar_at_level instead
# @register_detector
class PinbarDetector(BaseDetector):
    """
    Detects pinbar (hammer/shooting star) candlestick patterns.
    """
    
    name = "pinbar"
    description = "Detects pinbar patterns (hammer, shooting star)"

    meta = DetectorMeta(
        family="pattern",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.65,
        selftests=[
            SelfTestCase(fixture_id="pinbar_hammer", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="range_mid_nohit", expect_match=False),
        ],
    )
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if not candles:
            return DetectorResult(detector_name=self.name, match=False)
        
        last_candle = candles[-1]
        patterns = detect_single_candle_patterns(last_candle)
        
        # Look for hammer (bullish pinbar)
        for pattern in patterns:
            if pattern.pattern == "hammer":
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction="BUY",
                    confidence=0.65,
                    score_contrib=float(self.meta.default_score),
                    tags=[self.meta.family],
                    evidence_dict={"family": self.meta.family},
                    evidence=["PINBAR_HAMMER", f"TIME={pattern.at_time}"],
                    meta={"pattern": "hammer", "candle": last_candle},
                )
            elif pattern.pattern == "shooting_star":
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction="SELL",
                    confidence=0.65,
                    score_contrib=float(self.meta.default_score),
                    tags=[self.meta.family],
                    evidence_dict={"family": self.meta.family},
                    evidence=["PINBAR_SHOOTING_STAR", f"TIME={pattern.at_time}"],
                    meta={"pattern": "shooting_star", "candle": last_candle},
                )
        
        return DetectorResult(detector_name=self.name, match=False)


# MERGED: use engulf_at_level instead
# @register_detector
class EngulfingDetector(BaseDetector):
    """
    Detects engulfing candlestick patterns.
    """
    
    name = "engulfing"
    description = "Detects bullish/bearish engulfing patterns"

    meta = DetectorMeta(
        family="pattern",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.70,
        selftests=[
            SelfTestCase(fixture_id="engulfing_buy", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="range_mid_nohit", expect_match=False),
        ],
    )
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if len(candles) < 2:
            return DetectorResult(detector_name=self.name, match=False)
        
        from engine_blocks import detect_multi_candle_patterns
        
        patterns = detect_multi_candle_patterns(candles)
        
        for pattern in patterns:
            if pattern.pattern == "bullish_engulfing":
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction="BUY",
                    confidence=0.70,
                    score_contrib=float(self.meta.default_score),
                    tags=[self.meta.family],
                    evidence_dict={"family": self.meta.family},
                    evidence=["BULLISH_ENGULFING", f"TIME={pattern.at_time}"],
                    meta={"pattern": "bullish_engulfing"},
                )
            elif pattern.pattern == "bearish_engulfing":
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction="SELL",
                    confidence=0.70,
                    score_contrib=float(self.meta.default_score),
                    tags=[self.meta.family],
                    evidence_dict={"family": self.meta.family},
                    evidence=["BEARISH_ENGULFING", f"TIME={pattern.at_time}"],
                    meta={"pattern": "bearish_engulfing"},
                )
        
        return DetectorResult(detector_name=self.name, match=False)


@register_detector
class DojiDetector(BaseDetector):
    """
    Detects doji candlestick patterns (indecision).
    """
    
    name = "doji"
    description = "Detects doji patterns (market indecision)"

    meta = DetectorMeta(
        family="pattern",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.50,
        selftests=[
            SelfTestCase(fixture_id="doji", expect_match=True, expect_direction=None),
            SelfTestCase(fixture_id="engulfing_buy", expect_match=False),
        ],
    )
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if not candles:
            return DetectorResult(detector_name=self.name, match=False)
        
        last_candle = candles[-1]
        patterns = detect_single_candle_patterns(last_candle)
        
        for pattern in patterns:
            if pattern.pattern == "doji":
                # Doji is neutral - confidence low, no direction
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction=None,  # Neutral
                    confidence=0.50,
                    score_contrib=float(self.meta.default_score),
                    tags=[self.meta.family],
                    evidence_dict={"family": self.meta.family},
                    evidence=["DOJI_INDECISION", f"TIME={pattern.at_time}"],
                    meta={"pattern": "doji", "meaning": "indecision"},
                )
        
        return DetectorResult(detector_name=self.name, match=False)


@register_detector
class PinbarAtLevelDetector(BaseDetector):
    """Pinbar pattern that occurs at key level (Fibo or S/R)."""

    name = "pinbar_at_level"
    description = "Detects pinbar patterns at key S/R or Fib levels"

    meta = DetectorMeta(
        family="pattern",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.72,
        param_schema={
            # Smaller => stricter (requires closer proximity to key level).
            "level_tolerance": {
                "type": "float",
                "min": 0.0002,
                "max": 0.02,
                "strict_low": 0.001,
                "default": 0.0015,
            }
        },
        selftests=[
            SelfTestCase(fixture_id="fibo_confluence_buy", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="range_mid_nohit", expect_match=False),
        ],
    )

    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if len(candles) < 2:
            return DetectorResult(detector_name=self.name, match=False)

        last_candle = candles[-1]
        patterns = detect_single_candle_patterns(last_candle)

        is_hammer = any(p.pattern == "hammer" for p in patterns)
        is_star = any(p.pattern == "shooting_star" for p in patterns)
        if not is_hammer and not is_star:
            return DetectorResult(detector_name=self.name, match=False)

        tol = float(self.config.get("level_tolerance", 0.0015))

        key_levels: List[float] = []

        # Clustered S/R zones
        if primitives.sr_zones_clustered:
            for z in primitives.sr_zones_clustered[:8]:
                key_levels.append(z.level)
                key_levels.append(z.lower)
                key_levels.append(z.upper)
        else:
            key_levels.append(primitives.sr_zones.support)
            key_levels.append(primitives.sr_zones.resistance)

        # Fib retrace levels
        if primitives.fib_levels and primitives.fib_levels.retrace:
            key_levels.extend(primitives.fib_levels.retrace.values())

        key_levels = [x for x in key_levels if isinstance(x, (int, float)) and x > 0]
        if not key_levels:
            return DetectorResult(detector_name=self.name, match=False)

        # Must touch a level (wick/price proximity)
        touched_level = None
        for lvl in key_levels:
            if abs(last_candle.low - lvl) / lvl <= tol or abs(last_candle.high - lvl) / lvl <= tol:
                touched_level = lvl
                break

        if touched_level is None:
            return DetectorResult(detector_name=self.name, match=False)

        if is_hammer:
            return DetectorResult(
                detector_name=self.name,
                match=True,
                direction="BUY",
                confidence=0.72,
                score_contrib=float(self.meta.default_score),
                tags=[self.meta.family],
                evidence_dict={"family": self.meta.family},
                evidence=["PINBAR_AT_LEVEL", "HAMMER", f"LEVEL@{touched_level:.5f}"],
                meta={"level": touched_level, "pattern": "hammer"},
            )

        return DetectorResult(
            detector_name=self.name,
            match=True,
            direction="SELL",
            confidence=0.72,
            score_contrib=float(self.meta.default_score),
            tags=[self.meta.family],
            evidence_dict={"family": self.meta.family},
            evidence=["PINBAR_AT_LEVEL", "SHOOTING_STAR", f"LEVEL@{touched_level:.5f}"],
            meta={"level": touched_level, "pattern": "shooting_star"},
        )
