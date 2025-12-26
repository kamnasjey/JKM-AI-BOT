"""rectangle_range_edge.py

Detects range-bound market and trades edges (support/resistance).

Priority B: RECTANGLE_RANGE_EDGE

Heuristic:
- Uses basic S/R band (support/resistance)
- If price is near an edge and range width is non-trivial, fade back toward mid/opposite edge
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle

from .base import BaseDetector, DetectorSignal
from .utils import build_tp, entry_tf_from_profile, is_near_level_price, min_rr_from_profile


class RectangleRangeEdgeDetector(BaseDetector):
    name = "rectangle_range_edge"

    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        from core.primitives import PrimitiveResults

        if not isinstance(primitives, PrimitiveResults):
            return None

        if len(entry_candles) < 40:
            return None

        sr = primitives.sr_zones
        if sr.support <= 0 or sr.resistance <= 0:
            return None

        width = sr.resistance - sr.support
        if width <= 0:
            return None

        last = entry_candles[-1]
        price = last.close

        tol = float(self.config.params.get("edge_tolerance", 0.0015))
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0005))

        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        mid = (sr.support + sr.resistance) / 2.0

        # BUY at support
        if is_near_level_price(price, sr.support, tol):
            entry = price
            sl = sr.support - width * sl_buffer
            # Prefer TP to mid to avoid overly ambitious targets
            tp = mid
            rr = abs(tp - entry) / max(abs(entry - sl), 1e-9)
            if rr < min_rr:
                # If mid doesn't give enough RR, use RR-based TP
                tp2 = build_tp(entry, sl, "BUY", min_rr)
                if tp2 is None:
                    return None
                tp = tp2
                rr = min_rr

            return DetectorSignal(
                detector_name=self.name,
                pair=pair,
                direction="BUY",
                entry=entry,
                sl=sl,
                tp=tp,
                rr=rr,
                strength=0.58,
                timeframe=tf,
                reasons=["RECTANGLE_RANGE_EDGE", f"BUY_SUPPORT|{sr.support:.5f}"],
                meta={"support": sr.support, "resistance": sr.resistance, "mid": mid},
            )

        # SELL at resistance
        if is_near_level_price(price, sr.resistance, tol):
            entry = price
            sl = sr.resistance + width * sl_buffer
            tp = mid
            rr = abs(entry - tp) / max(abs(sl - entry), 1e-9)
            if rr < min_rr:
                tp2 = build_tp(entry, sl, "SELL", min_rr)
                if tp2 is None:
                    return None
                tp = tp2
                rr = min_rr

            return DetectorSignal(
                detector_name=self.name,
                pair=pair,
                direction="SELL",
                entry=entry,
                sl=sl,
                tp=tp,
                rr=rr,
                strength=0.58,
                timeframe=tf,
                reasons=["RECTANGLE_RANGE_EDGE", f"SELL_RES|{sr.resistance:.5f}"],
                meta={"support": sr.support, "resistance": sr.resistance, "mid": mid},
            )

        return None
