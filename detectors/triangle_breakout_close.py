"""triangle_breakout_close.py

Detects triangle (converging highs/lows) and breakout close.

Priority A: TRIANGLE_BREAKOUT_CLOSE

Heuristic:
- Uses indicator-free fractal swings (structure_trend) when available
- Requires descending swing highs and ascending swing lows (convergence)
- Breakout: last close beyond projected upper/lower trendline
- TP: uses triangle height (measured from first swing high/low in pattern)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from engine_blocks import Candle

from .base import BaseDetector, DetectorSignal
from .utils import build_tp, entry_tf_from_profile, min_rr_from_profile


@dataclass(frozen=True)
class _Line:
    x1: int
    y1: float
    x2: int
    y2: float

    def value_at(self, x: int) -> float:
        if self.x2 == self.x1:
            return self.y2
        m = (self.y2 - self.y1) / (self.x2 - self.x1)
        return self.y1 + m * (x - self.x1)


def _fit_line(points: List[tuple[int, float]]) -> Optional[_Line]:
    if len(points) < 2:
        return None
    (x1, y1), (x2, y2) = points[-2], points[-1]
    return _Line(x1=x1, y1=y1, x2=x2, y2=y2)


class TriangleBreakoutCloseDetector(BaseDetector):
    name = "triangle_breakout_close"

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

        if len(entry_candles) < 60:
            return None

        if not primitives.structure_trend or not primitives.structure_trend.swing_highs or not primitives.structure_trend.swing_lows:
            return None

        highs = primitives.structure_trend.swing_highs[-6:]
        lows = primitives.structure_trend.swing_lows[-6:]
        if len(highs) < 3 or len(lows) < 3:
            return None

        # Ensure recent convergence: last 3 highs descending, last 3 lows ascending
        if not (highs[-3].price > highs[-2].price > highs[-1].price):
            return None
        if not (lows[-3].price < lows[-2].price < lows[-1].price):
            return None

        # Build simple trendlines from last 2 swing highs and last 2 swing lows
        upper = _fit_line([(h.index, h.price) for h in highs[-3:]])
        lower = _fit_line([(l.index, l.price) for l in lows[-3:]])
        if upper is None or lower is None:
            return None

        # Check that lines are converging
        x_now = len(entry_candles) - 1
        up_now = upper.value_at(x_now)
        lo_now = lower.value_at(x_now)
        if up_now <= lo_now:
            return None

        last = entry_candles[-1]
        prev = entry_candles[-2]

        breakout_tol = float(self.config.params.get("break_tolerance", 0.0008))
        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        # Triangle height approximated from first points in window
        tri_height = max(h.price for h in highs[-5:]) - min(l.price for l in lows[-5:])
        if tri_height <= 0:
            return None

        # Breakout close beyond line
        if last.close > up_now * (1 + breakout_tol) and prev.close <= up_now:
            entry = last.close
            sl = lo_now
            # Prefer measured move
            tp = entry + tri_height
            rr = abs(tp - entry) / max(abs(entry - sl), 1e-9)
            if rr < min_rr:
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
                strength=0.73,
                timeframe=tf,
                reasons=[
                    "TRIANGLE_BREAKOUT_CLOSE",
                    "BREAK_UP",
                ],
                meta={"upper": up_now, "lower": lo_now, "height": tri_height},
            )

        if last.close < lo_now * (1 - breakout_tol) and prev.close >= lo_now:
            entry = last.close
            sl = up_now
            tp = entry - tri_height
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
                strength=0.73,
                timeframe=tf,
                reasons=[
                    "TRIANGLE_BREAKOUT_CLOSE",
                    "BREAK_DOWN",
                ],
                meta={"upper": up_now, "lower": lo_now, "height": tri_height},
            )

        return None
