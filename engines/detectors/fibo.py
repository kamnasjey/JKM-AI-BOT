"""
fibo.py
-------
Fibonacci-based detector plugins.
"""

from typing import Any, Dict, List, Optional

from .base import BaseDetector, DetectorMeta, DetectorResult, SelfTestCase
from .registry import register_detector
from engine_blocks import Candle
from core.primitives import PrimitiveResults
from core.types import Regime


# MERGED: use fibo_retrace_confluence instead (has S/R confluence)
# @register_detector
class FiboRetracementDetector(BaseDetector):
    """
    Detects price in Fibonacci retracement zones.
    
    Logic:
    - Price retraces into key Fibo level (0.5, 0.618, 0.786)
    - Direction aligns with original swing direction
    """
    
    name = "fibo_retrace"
    description = "Detects price in Fibo retracement zones"

    meta = DetectorMeta(
        family="fibo",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.70,
        selftests=[
            SelfTestCase(fixture_id="fibo_retrace_buy", expect_match=True, expect_direction=None),
            SelfTestCase(
                fixture_id="range_mid_nohit",
                expect_match=False,
                config_overrides={"tolerance": 0.0001},
            ),
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
        
        last_close = candles[-1].close
        fib_levels = primitives.fib_levels
        
        if not fib_levels.retrace:
            return DetectorResult(detector_name=self.name, match=False)
        
        # Check key retracement levels
        key_levels = self.config.get("key_levels", [0.5, 0.618, 0.786])
        tolerance = self.config.get("tolerance", 0.002)  # 0.2%
        
        for level_pct in key_levels:
            if level_pct not in fib_levels.retrace:
                continue
            
            level_price = fib_levels.retrace[level_pct]
            
            # Check if price is near this level
            if abs(last_close - level_price) / level_price <= tolerance:
                # Determine direction based on swing
                # Retracing upswing → expect continuation up (BUY)
                # Retracing downswing → expect continuation down (SELL)
                
                # Use structure trend as proxy for swing direction
                direction_hint = primitives.structure_trend.direction if primitives.structure_trend else "flat"
                
                if direction_hint == "up":
                    direction = "BUY"
                elif direction_hint == "down":
                    direction = "SELL"
                else:
                    direction = None
                
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction=direction,
                    confidence=0.6 + (level_pct - 0.5) * 0.2,  # Higher confidence for deeper retracements
                    score_contrib=float(self.meta.default_score),
                    tags=[self.meta.family],
                    evidence_dict={"family": self.meta.family},
                    evidence=[
                        f"FIBO_{level_pct}",
                        f"LEVEL@{level_price:.5f}",
                        f"PRICE@{last_close:.5f}",
                    ],
                    meta={"fib_level": level_pct, "fib_price": level_price},
                )
        
        return DetectorResult(detector_name=self.name, match=False)


@register_detector
class FiboExtensionDetector(BaseDetector):
    """
    Detects price reaching Fibonacci extension targets.
    
    Used for take-profit zones.
    """
    
    name = "fibo_extension"
    description = "Detects price at Fibo extension targets"

    meta = DetectorMeta(
        family="fibo",
        supported_regimes={
            Regime.TREND_BULL.value,
            Regime.TREND_BEAR.value,
            Regime.RANGE.value,
            Regime.CHOP.value,
        },
        default_score=0.70,
        selftests=[
            SelfTestCase(fixture_id="fibo_extension_hit", expect_match=True, expect_direction=None),
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
        
        last_close = candles[-1].close
        fib_levels = primitives.fib_levels
        
        if not fib_levels.extensions:
            return DetectorResult(detector_name=self.name, match=False)
        
        # Check extension levels (TP zones)
        extensions = self.config.get("extensions", [1.272, 1.618, 2.0])
        tolerance = self.config.get("tolerance", 0.003)
        
        for ext_pct in extensions:
            if ext_pct not in fib_levels.extensions:
                continue
            
            ext_price = fib_levels.extensions[ext_pct]
            
            if abs(last_close - ext_price) / ext_price <= tolerance:
                # Reached extension - potential reversal or TP zone
                return DetectorResult(
                    detector_name=self.name,
                    match=True,
                    direction=None,  # No directional bias - this is a target
                    confidence=0.70,
                    score_contrib=float(self.meta.default_score),
                    tags=[self.meta.family],
                    evidence_dict={"family": self.meta.family},
                    evidence=[
                        f"FIBO_EXT_{ext_pct}",
                        f"TARGET@{ext_price:.5f}",
                        "POTENTIAL_TP_ZONE",
                    ],
                    meta={"extension": ext_pct, "target_price": ext_price},
                )
        
        return DetectorResult(detector_name=self.name, match=False)


@register_detector
class FiboRetraceConfluenceDetector(BaseDetector):
    """Fibo retracement with S/R confluence (stronger than fibo_retrace)."""

    name = "fibo_retrace_confluence"
    description = "Detects fib retrace entries with S/R confluence"

    meta = DetectorMeta(
        family="fibo",
        supported_regimes={Regime.TREND_BULL.value, Regime.TREND_BEAR.value},
        default_score=0.80,
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
        if not candles:
            return DetectorResult(detector_name=self.name, match=False)

        last_close = candles[-1].close

        fib_levels = primitives.fib_levels
        if not fib_levels.retrace:
            return DetectorResult(detector_name=self.name, match=False)

        # Trend direction hint
        trend_dir = primitives.structure_trend.direction if primitives.structure_trend else "flat"
        if trend_dir not in ("up", "down"):
            return DetectorResult(detector_name=self.name, match=False)

        key_levels = self.config.get("key_levels", [0.5, 0.618])
        tolerance = float(self.config.get("tolerance", 0.0015))

        fib_hit = None
        for lvl_pct in key_levels:
            if lvl_pct not in fib_levels.retrace:
                continue
            lvl_price = fib_levels.retrace[lvl_pct]
            if lvl_price and abs(last_close - lvl_price) / lvl_price <= tolerance:
                fib_hit = (lvl_pct, lvl_price)
                break

        if fib_hit is None:
            return DetectorResult(detector_name=self.name, match=False)

        # S/R confluence
        zones = primitives.sr_zones_clustered or []
        sr_hit = None
        if zones:
            for z in zones[:10]:
                if trend_dir == "up" and not z.is_resistance:
                    if abs(last_close - z.level) / z.level <= tolerance:
                        sr_hit = z.level
                        break
                if trend_dir == "down" and z.is_resistance:
                    if abs(last_close - z.level) / z.level <= tolerance:
                        sr_hit = z.level
                        break
        else:
            sr = primitives.sr_zones
            if trend_dir == "up" and sr.support and abs(last_close - sr.support) / sr.support <= tolerance:
                sr_hit = sr.support
            if trend_dir == "down" and sr.resistance and abs(last_close - sr.resistance) / sr.resistance <= tolerance:
                sr_hit = sr.resistance

        if sr_hit is None:
            return DetectorResult(detector_name=self.name, match=False)

        direction = "BUY" if trend_dir == "up" else "SELL"

        # Extension target preference (evidence only)
        ext_target = None
        for ext in (1.618, 1.272, 2.0):
            if ext in (fib_levels.extensions or {}):
                ext_target = fib_levels.extensions[ext]
                break

        confidence = 0.78
        if fib_hit[0] >= 0.618:
            confidence = 0.82

        evidence = [
            "FIBO_RETRACE_CONFLUENCE",
            f"FIBO_{fib_hit[0]}@{fib_hit[1]:.5f}",
            f"SR@{sr_hit:.5f}",
        ]
        if ext_target:
            evidence.append(f"EXT_TARGET@{ext_target:.5f}")

        return DetectorResult(
            detector_name=self.name,
            match=True,
            direction=direction,
            confidence=confidence,
            score_contrib=float(self.meta.default_score),
            tags=[self.meta.family],
            evidence_dict={"family": self.meta.family},
            evidence=evidence,
            meta={"fib": fib_hit, "sr": sr_hit, "trend_dir": trend_dir, "ext_target": ext_target},
        )
