"""double_top_bottom.py

Detects double top / double bottom patterns using fractal swings.

Priority B: DOUBLE_TOP_BOTTOM

Heuristic:
- Needs two recent swing highs (double top) within tolerance and a neckline low between them
- Trigger when last close breaks neckline

Inverse for double bottom.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle

from .base import BaseDetector, DetectorSignal
from .utils import build_tp, entry_tf_from_profile, min_rr_from_profile, within


class DoubleTopBottomDetector(BaseDetector):
    name = "double_top_bottom"

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

        if not primitives.structure_trend or not primitives.structure_trend.swing_highs or not primitives.structure_trend.swing_lows:
            return None

        highs = primitives.structure_trend.swing_highs
        lows = primitives.structure_trend.swing_lows
        if len(highs) < 3 or len(lows) < 3:
            return None

        tol = float(self.config.params.get("peak_tolerance", 0.002))  # 0.2%
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0005))
        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        last = entry_candles[-1]
        price = last.close

        # Double Top: last two significant highs similar
        h2 = highs[-1]
        h1 = highs[-2]
        if within(h1.price, h2.price, tol):
            # neckline = lowest swing low between h1 and h2 indices
            neck = None
            for l in lows:
                if h1.index < l.index < h2.index:
                    if neck is None or l.price < neck:
                        neck = l.price
            if neck and price < neck:
                entry = price
                sl = max(h1.price, h2.price) * (1 + sl_buffer)
                tp = build_tp(entry, sl, "SELL", min_rr)
                if tp is None:
                    return None
                return DetectorSignal(
                    detector_name=self.name,
                    pair=pair,
                    direction="SELL",
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    rr=min_rr,
                    strength=0.66,
                    timeframe=tf,
                    reasons=["DOUBLE_TOP_BOTTOM", "DOUBLE_TOP", f"NECK|{neck:.5f}"],
                    meta={"h1": h1.price, "h2": h2.price, "neckline": neck},
                )

        # Double Bottom
        l2 = lows[-1]
        l1 = lows[-2]
        if within(l1.price, l2.price, tol):
            neck = None
            for h in highs:
                if l1.index < h.index < l2.index:
                    if neck is None or h.price > neck:
                        neck = h.price
            if neck and price > neck:
                entry = price
                sl = min(l1.price, l2.price) * (1 - sl_buffer)
                tp = build_tp(entry, sl, "BUY", min_rr)
                if tp is None:
                    return None
                return DetectorSignal(
                    detector_name=self.name,
                    pair=pair,
                    direction="BUY",
                    entry=entry,
                    sl=sl,
                    tp=tp,
                    rr=min_rr,
                    strength=0.66,
                    timeframe=tf,
                    reasons=["DOUBLE_TOP_BOTTOM", "DOUBLE_BOTTOM", f"NECK|{neck:.5f}"],
                    meta={"l1": l1.price, "l2": l2.price, "neckline": neck},
                )

        return None
