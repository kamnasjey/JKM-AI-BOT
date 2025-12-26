"""fakeout_trap.py

Detects a fake breakout (trap) at a key S/R zone.

Priority A: FAKEOUT_TRAP

Heuristic:
- Candle[-2] closes beyond S/R (breakout)
- Candle[-1] closes back inside range (failure)
- Trade opposite direction (fade the breakout)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle

from .base import BaseDetector, DetectorSignal
from .utils import Level, build_tp, entry_tf_from_profile, min_rr_from_profile


def _levels_from_primitives(primitives: Any) -> List[Level]:
    from core.primitives import PrimitiveResults

    if not isinstance(primitives, PrimitiveResults):
        return []

    if primitives.sr_zones_clustered:
        levels: List[Level] = []
        for z in primitives.sr_zones_clustered[:12]:
            kind = "resistance" if z.is_resistance else "support"
            levels.append(Level(level=z.level, lower=z.lower, upper=z.upper, kind=kind, strength=z.strength))
        return levels

    sr = primitives.sr_zones
    levels = []
    if sr.support > 0:
        levels.append(Level(level=sr.support, lower=sr.support * 0.999, upper=sr.support * 1.001, kind="support"))
    if sr.resistance > 0:
        levels.append(Level(level=sr.resistance, lower=sr.resistance * 0.999, upper=sr.resistance * 1.001, kind="resistance"))
    return levels


class FakeoutTrapDetector(BaseDetector):
    name = "fakeout_trap"

    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        if len(entry_candles) < 10:
            return None

        levels = _levels_from_primitives(primitives)
        if not levels:
            return None

        break_tol = float(self.config.params.get("break_tolerance", 0.0008))
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0004))

        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        c_break = entry_candles[-2]
        c_fail = entry_candles[-1]

        levels_sorted = sorted(levels, key=lambda x: x.strength, reverse=True)

        for lvl in levels_sorted:
            if lvl.level <= 0:
                continue

            # Fake breakout above resistance -> SELL
            if lvl.kind == "resistance":
                broke = c_break.close > lvl.upper * (1 + break_tol)
                failed = c_fail.close < lvl.upper
                if broke and failed:
                    entry = c_fail.close
                    sl = max(c_break.high, c_fail.high) * (1 + sl_buffer)
                    tp = build_tp(entry, sl, "SELL", min_rr)
                    if tp is None:
                        continue
                    return DetectorSignal(
                        detector_name=self.name,
                        pair=pair,
                        direction="SELL",
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        rr=min_rr,
                        strength=0.7,
                        timeframe=tf,
                        reasons=["FAKEOUT_TRAP", f"FAKE_UP|{lvl.level:.5f}"],
                        meta={"level": lvl.level, "zone_lower": lvl.lower, "zone_upper": lvl.upper},
                    )

            # Fake breakout below support -> BUY
            if lvl.kind == "support":
                broke = c_break.close < lvl.lower * (1 - break_tol)
                failed = c_fail.close > lvl.lower
                if broke and failed:
                    entry = c_fail.close
                    sl = min(c_break.low, c_fail.low) * (1 - sl_buffer)
                    tp = build_tp(entry, sl, "BUY", min_rr)
                    if tp is None:
                        continue
                    return DetectorSignal(
                        detector_name=self.name,
                        pair=pair,
                        direction="BUY",
                        entry=entry,
                        sl=sl,
                        tp=tp,
                        rr=min_rr,
                        strength=0.7,
                        timeframe=tf,
                        reasons=["FAKEOUT_TRAP", f"FAKE_DOWN|{lvl.level:.5f}"],
                        meta={"level": lvl.level, "zone_lower": lvl.lower, "zone_upper": lvl.upper},
                    )

        return None
