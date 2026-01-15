"""range.py
--------
Range / chop detector plugins.

These are designed to be safe when structure trend is unclear.
They avoid indicators and use only price/structure primitives.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import BaseDetector, DetectorMeta, DetectorResult, SelfTestCase
from .registry import register_detector
from engine_blocks import Candle
from core.primitives import PrimitiveResults
from core.types import Regime


def _rr(entry: float, sl: float, tp: float) -> float:
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0:
        return 0.0
    return reward / risk


# MERGED: use rectangle_range_edge instead
# @register_detector
class RangeBoxEdgeDetector(BaseDetector):
    """Trades range edges using a simple support/resistance "box".

    Uses primitives.sr_zones (min/max over lookback) as the range box.

    BUY when price is near support.
    SELL when price is near resistance.
    """

    name = "range_box_edge"
    description = "Detects range box edges (fade support/resistance)"
    meta = DetectorMeta(
        family="range",
        supported_regimes={Regime.RANGE.value, Regime.CHOP.value},
        default_score=0.68,
        param_schema={
            # Higher => stricter (filters out more ranges).
            "min_width_frac": {
                "type": "float",
                "min": 0.0005,
                "max": 0.02,
                "strict_high": 0.006,
                "default": 0.002,
            },
            # Smaller => stricter (requires closer edge proximity).
            "edge_tolerance_frac": {
                "type": "float",
                "min": 0.0002,
                "max": 0.01,
                "strict_low": 0.0008,
                "default": 0.0015,
            },
            "sl_width_frac": {
                "type": "float",
                "min": 0.05,
                "max": 0.5,
                "default": 0.10,
            },
        },
        selftests=[
            SelfTestCase(fixture_id="range_edge_buy", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="range_mid_nohit", expect_match=False),
        ],
    )

    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if len(candles) < 10:
            return DetectorResult(detector_name=self.name, match=False)

        sr = primitives.sr_zones
        support = float(sr.support or 0.0)
        resistance = float(sr.resistance or 0.0)
        last = candles[-1]

        if support <= 0 or resistance <= 0 or resistance <= support:
            return DetectorResult(detector_name=self.name, match=False)

        mid = (support + resistance) / 2.0
        width = resistance - support

        min_width_frac = float(self.config.get("min_width_frac", 0.002))  # 0.2%
        if width / mid < min_width_frac:
            return DetectorResult(detector_name=self.name, match=False)

        edge_tolerance_frac = float(self.config.get("edge_tolerance_frac", 0.0015))  # 0.15%

        # Near support => BUY
        if abs(last.close - support) / support <= edge_tolerance_frac:
            entry = float(last.close)
            sl = support - width * float(self.config.get("sl_width_frac", 0.10))
            tp = resistance
            rr_val = _rr(entry, sl, tp)
            return DetectorResult(
                detector_name=self.name,
                match=True,
                direction="BUY",
                confidence=0.68,
                score_contrib=float(self.meta.default_score),
                tags=[self.meta.family],
                evidence_dict={"family": self.meta.family},
                setup_name="RANGE_BOX_EDGE_BUY",
                evidence=[
                    "RANGE_BOX_EDGE",
                    f"SUP@{support:.5f}",
                    f"RES@{resistance:.5f}",
                    f"WIDTH={width / mid:.4f}",
                ],
                entry=entry,
                sl=sl,
                tp=tp,
                rr=rr_val,
                meta={"support": support, "resistance": resistance, "mid": mid, "width": width},
            )

        # Near resistance => SELL
        if abs(last.close - resistance) / resistance <= edge_tolerance_frac:
            entry = float(last.close)
            sl = resistance + width * float(self.config.get("sl_width_frac", 0.10))
            tp = support
            rr_val = _rr(entry, sl, tp)
            return DetectorResult(
                detector_name=self.name,
                match=True,
                direction="SELL",
                confidence=0.68,
                score_contrib=float(self.meta.default_score),
                tags=[self.meta.family],
                evidence_dict={"family": self.meta.family},
                setup_name="RANGE_BOX_EDGE_SELL",
                evidence=[
                    "RANGE_BOX_EDGE",
                    f"SUP@{support:.5f}",
                    f"RES@{resistance:.5f}",
                    f"WIDTH={width / mid:.4f}",
                ],
                entry=entry,
                sl=sl,
                tp=tp,
                rr=rr_val,
                meta={"support": support, "resistance": resistance, "mid": mid, "width": width},
            )

        return DetectorResult(detector_name=self.name, match=False)


@register_detector
class FakeoutTrapDetector(BaseDetector):
    """Detects a simple fakeout: wick beyond the range, close back inside."""

    name = "fakeout_trap"
    description = "Detects fakeout traps at range edges"
    meta = DetectorMeta(
        family="range",
        supported_regimes={Regime.RANGE.value, Regime.CHOP.value},
        default_score=0.72,
        param_schema={
            # Higher => stricter (filters out more ranges).
            "min_width_frac": {
                "type": "float",
                "min": 0.0005,
                "max": 0.02,
                "strict_high": 0.006,
                "default": 0.002,
            },
            # Higher => stricter (requires deeper pierce beyond edge).
            "pierce_frac": {
                "type": "float",
                "min": 0.0,
                "max": 0.01,
                "strict_high": 0.003,
                "default": 0.0010,
            },
            # Higher => stricter (requires stronger close back inside).
            "close_back_frac": {
                "type": "float",
                "min": 0.0,
                "max": 0.01,
                "strict_high": 0.001,
                "default": 0.0003,
            },
            "sl_width_frac": {
                "type": "float",
                "min": 0.05,
                "max": 0.5,
                "default": 0.12,
            },
        },
        selftests=[
            SelfTestCase(fixture_id="fakeout_buy", expect_match=True, expect_direction="BUY"),
            SelfTestCase(fixture_id="range_mid_nohit", expect_match=False),
        ],
    )

    def detect(
        self,
        candles: List[Candle],
        primitives: PrimitiveResults,
        context: Optional[Dict[str, Any]] = None,
    ) -> DetectorResult:
        if len(candles) < 3:
            return DetectorResult(detector_name=self.name, match=False)

        # IMPORTANT:
        # primitives.sr_zones defines support/resistance as min/max over the lookback
        # INCLUDING the most recent candles. That makes a "pierce beyond support" check
        # impossible, because the piercing candle becomes the new support.
        # For fakeouts, compute the box from candles BEFORE the last two bars.
        base = candles[:-2]
        if len(base) >= 10:
            base_seg = base[-50:]
            support = float(min(c.low for c in base_seg))
            resistance = float(max(c.high for c in base_seg))
        else:
            sr = primitives.sr_zones
            support = float(sr.support or 0.0)
            resistance = float(sr.resistance or 0.0)
        if support <= 0 or resistance <= 0 or resistance <= support:
            return DetectorResult(detector_name=self.name, match=False)

        last = candles[-1]
        prev = candles[-2]

        mid = (support + resistance) / 2.0
        width = resistance - support
        if width / mid < float(self.config.get("min_width_frac", 0.002)):
            return DetectorResult(detector_name=self.name, match=False)

        pierce_frac = float(self.config.get("pierce_frac", 0.0010))
        close_back_frac = float(self.config.get("close_back_frac", 0.0003))

        # Bullish fakeout: pierce support then close back above support
        pierced_support = prev.low < support * (1.0 - pierce_frac) or last.low < support * (1.0 - pierce_frac)
        closed_back = last.close > support * (1.0 + close_back_frac)
        if pierced_support and closed_back:
            entry = float(last.close)
            sl = support - width * float(self.config.get("sl_width_frac", 0.12))
            tp = resistance
            rr_val = _rr(entry, sl, tp)
            return DetectorResult(
                detector_name=self.name,
                match=True,
                direction="BUY",
                confidence=0.72,
                score_contrib=float(self.meta.default_score),
                tags=[self.meta.family],
                evidence_dict={"family": self.meta.family},
                setup_name="FAKEOUT_TRAP_BUY",
                evidence=[
                    "FAKEOUT_TRAP",
                    f"SUP@{support:.5f}",
                    f"CLOSE@{entry:.5f}",
                    "CLOSE_BACK_INSIDE",
                ],
                entry=entry,
                sl=sl,
                tp=tp,
                rr=rr_val,
                meta={"support": support, "resistance": resistance, "width": width},
            )

        # Bearish fakeout: pierce resistance then close back below resistance
        pierced_res = prev.high > resistance * (1.0 + pierce_frac) or last.high > resistance * (1.0 + pierce_frac)
        closed_back = last.close < resistance * (1.0 - close_back_frac)
        if pierced_res and closed_back:
            entry = float(last.close)
            sl = resistance + width * float(self.config.get("sl_width_frac", 0.12))
            tp = support
            rr_val = _rr(entry, sl, tp)
            return DetectorResult(
                detector_name=self.name,
                match=True,
                direction="SELL",
                confidence=0.72,
                score_contrib=float(self.meta.default_score),
                tags=[self.meta.family],
                evidence_dict={"family": self.meta.family},
                setup_name="FAKEOUT_TRAP_SELL",
                evidence=[
                    "FAKEOUT_TRAP",
                    f"RES@{resistance:.5f}",
                    f"CLOSE@{entry:.5f}",
                    "CLOSE_BACK_INSIDE",
                ],
                entry=entry,
                sl=sl,
                tp=tp,
                rr=rr_val,
                meta={"support": support, "resistance": resistance, "width": width},
            )

        return DetectorResult(detector_name=self.name, match=False)
