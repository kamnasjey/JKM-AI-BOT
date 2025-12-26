"""head_shoulders.py

Detects (approximate) head-and-shoulders / inverse head-and-shoulders.

Priority B: HEAD_SHOULDERS

Heuristic:
- Uses last 3 swing highs for standard H&S: left shoulder, head, right shoulder
- Head higher than shoulders, shoulders similar
- Neckline = swing lows between peaks
- Trigger on close below neckline

Inverse for bullish.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle

from .base import BaseDetector, DetectorSignal
from .utils import build_tp, entry_tf_from_profile, min_rr_from_profile, within


class HeadShouldersDetector(BaseDetector):
    name = "head_shoulders"

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

        st = primitives.structure_trend
        if not st or len(st.swing_highs) < 4 or len(st.swing_lows) < 4:
            return None

        tol = float(self.config.params.get("shoulder_tolerance", 0.003))
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0006))
        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        last = entry_candles[-1]
        price = last.close

        highs = st.swing_highs
        lows = st.swing_lows

        # Standard H&S: last 3 swing highs form shoulders/head
        ls, head, rs = highs[-3], highs[-2], highs[-1]
        if head.price > ls.price and head.price > rs.price and within(ls.price, rs.price, tol):
            # neckline: lowest lows between ls->head and head->rs
            neck1 = None
            for l in lows:
                if ls.index < l.index < head.index:
                    if neck1 is None or l.price < neck1:
                        neck1 = l.price
            neck2 = None
            for l in lows:
                if head.index < l.index < rs.index:
                    if neck2 is None or l.price < neck2:
                        neck2 = l.price
            if neck1 and neck2:
                neckline = min(neck1, neck2)
                if price < neckline:
                    entry = price
                    sl = head.price * (1 + sl_buffer)
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
                        strength=0.68,
                        timeframe=tf,
                        reasons=["HEAD_SHOULDERS", "HNS_BREAK", f"NECK|{neckline:.5f}"],
                        meta={"ls": ls.price, "head": head.price, "rs": rs.price, "neckline": neckline},
                    )

        # Inverse H&S
        lb, headb, rb = lows[-3], lows[-2], lows[-1]
        if headb.price < lb.price and headb.price < rb.price and within(lb.price, rb.price, tol):
            neck1 = None
            for h in highs:
                if lb.index < h.index < headb.index:
                    if neck1 is None or h.price > neck1:
                        neck1 = h.price
            neck2 = None
            for h in highs:
                if headb.index < h.index < rb.index:
                    if neck2 is None or h.price > neck2:
                        neck2 = h.price
            if neck1 and neck2:
                neckline = max(neck1, neck2)
                if price > neckline:
                    entry = price
                    sl = headb.price * (1 - sl_buffer)
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
                        strength=0.68,
                        timeframe=tf,
                        reasons=["HEAD_SHOULDERS", "IHNS_BREAK", f"NECK|{neckline:.5f}"],
                        meta={"lb": lb.price, "head": headb.price, "rb": rb.price, "neckline": neckline},
                    )

        return None
