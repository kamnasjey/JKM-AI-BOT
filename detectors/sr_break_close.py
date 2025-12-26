"""sr_break_close.py

Detects clean close beyond a key S/R zone.

Priority A: SR_BREAK_CLOSE
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

    levels: List[Level] = []

    if primitives.sr_zones_clustered:
        for z in primitives.sr_zones_clustered[:12]:
            kind = "resistance" if z.is_resistance else "support"
            levels.append(Level(level=z.level, lower=z.lower, upper=z.upper, kind=kind, strength=z.strength))
        return levels

    sr = primitives.sr_zones
    if sr.support > 0:
        levels.append(Level(level=sr.support, lower=sr.support * 0.999, upper=sr.support * 1.001, kind="support"))
    if sr.resistance > 0:
        levels.append(Level(level=sr.resistance, lower=sr.resistance * 0.999, upper=sr.resistance * 1.001, kind="resistance"))
    return levels


class SRBreakCloseDetector(BaseDetector):
    name = "sr_break_close"

    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        if len(entry_candles) < 5:
            return None

        levels = _levels_from_primitives(primitives)
        if not levels:
            return None

        last = entry_candles[-1]
        prev = entry_candles[-2]

        break_tol = float(self.config.params.get("break_tolerance", 0.0008))  # 0.08%
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0004))

        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        # Prefer stronger zones first
        levels_sorted = sorted(levels, key=lambda x: x.strength, reverse=True)

        for lvl in levels_sorted:
            if lvl.level <= 0:
                continue

            if lvl.kind == "resistance":
                broke_now = last.close > (lvl.upper * (1 + break_tol))
                was_below = prev.close <= lvl.upper
                if broke_now and was_below:
                    entry = last.close
                    sl = lvl.lower * (1 - sl_buffer)
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
                        strength=0.62,
                        timeframe=tf,
                        reasons=[
                            "SR_BREAK_CLOSE",
                            f"BROKE_RES|{lvl.level:.5f}",
                        ],
                        meta={"level": lvl.level, "zone_lower": lvl.lower, "zone_upper": lvl.upper},
                    )

            if lvl.kind == "support":
                broke_now = last.close < (lvl.lower * (1 - break_tol))
                was_above = prev.close >= lvl.lower
                if broke_now and was_above:
                    entry = last.close
                    sl = lvl.upper * (1 + sl_buffer)
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
                        strength=0.62,
                        timeframe=tf,
                        reasons=[
                            "SR_BREAK_CLOSE",
                            f"BROKE_SUP|{lvl.level:.5f}",
                        ],
                        meta={"level": lvl.level, "zone_lower": lvl.lower, "zone_upper": lvl.upper},
                    )

        return None
