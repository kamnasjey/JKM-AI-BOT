"""
sr.py
-----
Support/Resistance detector plugins.
"""

from typing import Any, Dict, List, Optional

from .base import BaseDetector, DetectorMeta, DetectorResult, SelfTestCase
from .registry import register_detector
from engine_blocks import Candle
from core.primitives import PrimitiveResults
from core.types import Regime


@register_detector
class SRBounceDetector(BaseDetector):
    """
    Detects price bouncing off S/R zones.
    
    Logic:
    - Price touches S/R zone (clustered from fractals)
    - Rejection candle forms (wick + body ratio)
    - Direction based on zone type (support=BUY, resistance=SELL)
    """
    
    name = "sr_bounce"
    description = "Detects bounces off S/R zones"

    meta = DetectorMeta(
        family="sr",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.75,
        param_schema={
            # Smaller => stricter touch. If too small, hits can be near-zero.
            "touch_tolerance": {
                "type": "float",
                "min": 0.00005,
                "max": 0.01,
                "strict_low": 0.0005,
                "default": 0.001,
            },
        },
        selftests=[
            SelfTestCase(
                fixture_id="range_edge_buy",
                expect_match=True,
                expect_direction="BUY",
                config_overrides={"touch_tolerance": 0.01},
            ),
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
        zones = primitives.sr_zones_clustered or []
        
        if not zones:
            return DetectorResult(detector_name=self.name, match=False)
        
        touch_tolerance = self.config.get("touch_tolerance", 0.001)  # 0.1%
        
        # Check if price touched any zone
        for zone in zones[:5]:  # Check top 5 strongest zones
            # Check if last candle touched the zone
            touched = False
            if zone.is_resistance:
                # Check if high touched resistance
                if abs(last_candle.high - zone.level) / zone.level <= touch_tolerance:
                    touched = True
            else:
                # Check if low touched support
                if abs(last_candle.low - zone.level) / zone.level <= touch_tolerance:
                    touched = True
            
            if not touched:
                continue
            
            # Check for rejection (wick > body)
            body = abs(last_candle.close - last_candle.open)
            total_range = last_candle.high - last_candle.low
            
            if total_range == 0:
                continue
            
            wick_ratio = (total_range - body) / total_range
            
            if wick_ratio > 0.5:  # Significant wick
                # Bullish bounce off support
                if not zone.is_resistance and last_candle.close > last_candle.open:
                    return DetectorResult(
                        detector_name=self.name,
                        match=True,
                        direction="BUY",
                        confidence=min(0.7 + (zone.strength - 1) * 0.05, 0.95),
                        score_contrib=float(self.meta.default_score),
                        tags=[self.meta.family],
                        evidence_dict={"family": self.meta.family},
                        evidence=[
                            f"SUPPORT_BOUNCE",
                            f"ZONE@{zone.level:.5f}",
                            f"STRENGTH={zone.strength}",
                            f"WICK_RATIO={wick_ratio:.2f}",
                        ],
                        meta={"zone": zone, "wick_ratio": wick_ratio},
                    )
                
                # Bearish bounce off resistance
                elif zone.is_resistance and last_candle.close < last_candle.open:
                    return DetectorResult(
                        detector_name=self.name,
                        match=True,
                        direction="SELL",
                        confidence=min(0.7 + (zone.strength - 1) * 0.05, 0.95),
                        score_contrib=float(self.meta.default_score),
                        tags=[self.meta.family],
                        evidence_dict={"family": self.meta.family},
                        evidence=[
                            f"RESISTANCE_BOUNCE",
                            f"ZONE@{zone.level:.5f}",
                            f"STRENGTH={zone.strength}",
                            f"WICK_RATIO={wick_ratio:.2f}",
                        ],
                        meta={"zone": zone, "wick_ratio": wick_ratio},
                    )
        
        return DetectorResult(detector_name=self.name, match=False)


@register_detector
class SRBreakoutDetector(BaseDetector):
    """
    Detects breakout through S/R zones.
    
    Logic:
    - Price breaks through S/R zone with strong candle
    - Volume/momentum confirmation (if available)
    - Direction based on break direction
    """
    
    name = "sr_breakout"
    description = "Detects breakouts through S/R zones"

    meta = DetectorMeta(
        family="sr",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.75,
        selftests=[
            SelfTestCase(fixture_id="sr_breakout_buy", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="range_mid_nohit", expect_match=False),
        ],
    )
    
    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if len(candles) < 5:
            return DetectorResult(detector_name=self.name, match=False)
        
        last_candle = candles[-1]
        prev_candles = candles[-5:-1]
        zones = primitives.sr_zones_clustered or []
        
        if not zones:
            return DetectorResult(detector_name=self.name, match=False)
        
        # Check recent breakout
        for zone in zones[:5]:
            # Was price below zone before?
            was_below = all(c.high < zone.lower for c in prev_candles[-3:])
            broke_above = last_candle.close > zone.upper
            
            # Was price above zone before?
            was_above = all(c.low > zone.upper for c in prev_candles[-3:])
            broke_below = last_candle.close < zone.lower
            
            # Bullish breakout
            if was_below and broke_above:
                body = abs(last_candle.close - last_candle.open)
                total = last_candle.high - last_candle.low
                body_ratio = body / total if total > 0 else 0
                
                if body_ratio > 0.6:  # Strong candle
                    return DetectorResult(
                        detector_name=self.name,
                        match=True,
                        direction="BUY",
                        confidence=0.75,
                        score_contrib=float(self.meta.default_score),
                        tags=[self.meta.family],
                        evidence_dict={"family": self.meta.family},
                        evidence=[
                            "RESISTANCE_BREAKOUT",
                            f"ZONE@{zone.level:.5f}",
                            f"BODY_RATIO={body_ratio:.2f}",
                        ],
                        meta={"zone": zone, "body_ratio": body_ratio},
                    )
            
            # Bearish breakout
            elif was_above and broke_below:
                body = abs(last_candle.close - last_candle.open)
                total = last_candle.high - last_candle.low
                body_ratio = body / total if total > 0 else 0
                
                if body_ratio > 0.6:
                    return DetectorResult(
                        detector_name=self.name,
                        match=True,
                        direction="SELL",
                        confidence=0.75,
                        score_contrib=float(self.meta.default_score),
                        tags=[self.meta.family],
                        evidence_dict={"family": self.meta.family},
                        evidence=[
                            "SUPPORT_BREAKOUT",
                            f"ZONE@{zone.level:.5f}",
                            f"BODY_RATIO={body_ratio:.2f}",
                        ],
                        meta={"zone": zone, "body_ratio": body_ratio},
                    )
        
        return DetectorResult(detector_name=self.name, match=False)


@register_detector
class SRRoleReversalDetector(BaseDetector):
    """Broken resistance becomes support / broken support becomes resistance."""

    name = "sr_role_reversal"
    description = "Detects S/R role reversal after breakout"

    meta = DetectorMeta(
        family="sr",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.78,
        param_schema={
            # Smaller => stricter (requires break to have happened very recently).
            "break_lookback": {
                "type": "int",
                "min": 3,
                "max": 50,
                "strict_low": 8,
                "default": 12,
            },
            # Larger => stricter (requires a bigger break beyond zone).
            "break_tolerance": {
                "type": "float",
                "min": 0.0,
                "max": 0.01,
                "strict_high": 0.002,
                "default": 0.0008,
            },
            # Smaller => stricter (requires closer retest).
            "touch_tolerance": {
                "type": "float",
                "min": 0.00005,
                "max": 0.01,
                "strict_low": 0.0008,
                "default": 0.0012,
            },
        },
        selftests=[
            SelfTestCase(fixture_id="sr_role_reversal_buy", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="sr_breakout_buy", expect_match=False),
        ],
    )

    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if len(candles) < 20:
            return DetectorResult(detector_name=self.name, match=False)

        zones = primitives.sr_zones_clustered or []
        if not zones:
            return DetectorResult(detector_name=self.name, match=False)

        lookback = int(self.config.get("break_lookback", 12))
        break_tol = float(self.config.get("break_tolerance", 0.0008))
        touch_tol = float(self.config.get("touch_tolerance", 0.0012))

        segment = candles[-max(lookback + 5, 20):]
        last = segment[-1]

        for zone in zones[:6]:
            if zone.level <= 0:
                continue

            # Resistance -> Support (bullish)
            if zone.is_resistance:
                broke = any(c.close > zone.upper * (1 + break_tol) for c in segment[-lookback:])
                if not broke:
                    continue

                touched = abs(last.low - zone.upper) / zone.upper <= touch_tol or abs(last.low - zone.level) / zone.level <= touch_tol
                holds = last.close >= zone.lower
                if touched and holds:
                    return DetectorResult(
                        detector_name=self.name,
                        match=True,
                        direction="BUY",
                        confidence=min(0.75 + (zone.strength - 1) * 0.03, 0.95),
                        score_contrib=float(self.meta.default_score),
                        tags=[self.meta.family],
                        evidence_dict={"family": self.meta.family},
                        evidence=[
                            "SR_ROLE_REVERSAL",
                            f"RES_TO_SUP@{zone.level:.5f}",
                            f"STRENGTH={zone.strength}",
                        ],
                        meta={"zone": zone},
                    )

            # Support -> Resistance (bearish)
            else:
                broke = any(c.close < zone.lower * (1 - break_tol) for c in segment[-lookback:])
                if not broke:
                    continue

                touched = abs(last.high - zone.lower) / zone.lower <= touch_tol or abs(last.high - zone.level) / zone.level <= touch_tol
                holds = last.close <= zone.upper
                if touched and holds:
                    return DetectorResult(
                        detector_name=self.name,
                        match=True,
                        direction="SELL",
                        confidence=min(0.75 + (zone.strength - 1) * 0.03, 0.95),
                        score_contrib=float(self.meta.default_score),
                        tags=[self.meta.family],
                        evidence_dict={"family": self.meta.family},
                        evidence=[
                            "SR_ROLE_REVERSAL",
                            f"SUP_TO_RES@{zone.level:.5f}",
                            f"STRENGTH={zone.strength}",
                        ],
                        meta={"zone": zone},
                    )

        return DetectorResult(detector_name=self.name, match=False)
