"""
price_action.py
---------------
Pure price action detector plugins.
"""

from typing import Any, Dict, List, Optional

from .base import BaseDetector, DetectorMeta, DetectorResult, SelfTestCase
from .registry import register_detector
from engine_blocks import Candle
from core.primitives import PrimitiveResults
from core.types import Regime


@register_detector
class StructureTrendDetector(BaseDetector):
    """
    Detects trend based on structure (HH/HL vs LH/LL).
    
    Pure indicator-free trend detection.
    """
    
    name = "structure_trend"
    description = "Detects trend from swing structure (HH/HL vs LH/LL)"

    meta = DetectorMeta(
        family="structure",
        supported_regimes={Regime.TREND_BULL.value, Regime.TREND_BEAR.value},
        default_score=0.70,
        selftests=[
            SelfTestCase(fixture_id="structure_up", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="range_mid_nohit", expect_match=False),
        ],
    )
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if not primitives.structure_trend:
            return DetectorResult(detector_name=self.name, match=False)
        
        struct = primitives.structure_trend
        
        if not struct.structure_valid:
            return DetectorResult(detector_name=self.name, match=False)
        
        # Clear uptrend
        if struct.direction == "up":
            confidence = min(0.6 + struct.hh_count * 0.05, 0.90)
            return DetectorResult(
                detector_name=self.name,
                match=True,
                direction="BUY",
                confidence=confidence,
                score_contrib=float(self.meta.default_score),
                tags=[self.meta.family],
                evidence_dict={"family": self.meta.family},
                evidence=[
                    "UPTREND_STRUCTURE",
                    f"HH={struct.hh_count}",
                    f"HL={struct.hl_count}",
                ],
                meta={"structure": struct},
            )
        
        # Clear downtrend
        elif struct.direction == "down":
            confidence = min(0.6 + struct.ll_count * 0.05, 0.90)
            return DetectorResult(
                detector_name=self.name,
                match=True,
                direction="SELL",
                confidence=confidence,
                score_contrib=float(self.meta.default_score),
                tags=[self.meta.family],
                evidence_dict={"family": self.meta.family},
                evidence=[
                    "DOWNTREND_STRUCTURE",
                    f"LH={struct.lh_count}",
                    f"LL={struct.ll_count}",
                ],
                meta={"structure": struct},
            )
        
        return DetectorResult(detector_name=self.name, match=False)


@register_detector
class SwingFailureDetector(BaseDetector):
    """
    Detects swing failure patterns (failed higher high / lower low).
    
    Classic reversal signal.
    """
    
    name = "swing_failure"
    description = "Detects swing failure patterns (reversal signal)"

    meta = DetectorMeta(
        family="structure",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.75,
        selftests=[
            SelfTestCase(fixture_id="swing_failure_buy", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="structure_up", expect_match=False),
        ],
    )
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if not primitives.structure_trend or len(candles) < 10:
            return DetectorResult(detector_name=self.name, match=False)
        
        struct = primitives.structure_trend
        swing_highs = struct.swing_highs
        swing_lows = struct.swing_lows
        
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return DetectorResult(detector_name=self.name, match=False)
        
        last_candle = candles[-1]
        
        # Bullish swing failure (failed lower low)
        # Price makes lower low but then reverses sharply
        if len(swing_lows) >= 2:
            last_low = swing_lows[-1]
            prev_low = swing_lows[-2]
            
            # Failed to make new low and reversed
            if last_low.price < prev_low.price:
                # Check if recent candles show strong reversal
                recent = candles[-5:]
                if any(c.close > last_low.price * 1.005 for c in recent):  # 0.5% bounce
                    return DetectorResult(
                        detector_name=self.name,
                        match=True,
                        direction="BUY",
                        confidence=0.75,
                        score_contrib=float(self.meta.default_score),
                        tags=[self.meta.family],
                        evidence_dict={"family": self.meta.family},
                        evidence=[
                            "BULLISH_SWING_FAILURE",
                            f"FAILED_LL@{last_low.price:.5f}",
                            "REVERSAL_UP",
                        ],
                        meta={"failed_low": last_low, "prev_low": prev_low},
                    )
        
        # Bearish swing failure (failed higher high)
        if len(swing_highs) >= 2:
            last_high = swing_highs[-1]
            prev_high = swing_highs[-2]
            
            if last_high.price > prev_high.price:
                recent = candles[-5:]
                if any(c.close < last_high.price * 0.995 for c in recent):  # 0.5% drop
                    return DetectorResult(
                        detector_name=self.name,
                        match=True,
                        direction="SELL",
                        confidence=0.75,
                        score_contrib=float(self.meta.default_score),
                        tags=[self.meta.family],
                        evidence_dict={"family": self.meta.family},
                        evidence=[
                            "BEARISH_SWING_FAILURE",
                            f"FAILED_HH@{last_high.price:.5f}",
                            "REVERSAL_DOWN",
                        ],
                        meta={"failed_high": last_high, "prev_high": prev_high},
                    )
        
        return DetectorResult(detector_name=self.name, match=False)
