"""sr_role_reversal.py

Detects role-reversal: broken resistance becomes support (bullish) or
broken support becomes resistance (bearish).

Priority A: SR_ROLE_REVERSAL
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle

from .base import BaseDetector, DetectorSignal
from .utils import Level, build_tp, entry_tf_from_profile, is_candle_touching_level, min_rr_from_profile


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


class SRRoleReversalDetector(BaseDetector):
    name = "sr_role_reversal"

    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        if len(entry_candles) < 25:
            return None

        levels = _levels_from_primitives(primitives)
        if not levels:
            return None

        lookback = int(self.config.params.get("break_lookback", 12))
        touch_tol = float(self.config.params.get("touch_tolerance", 0.0012))  # 0.12%
        break_tol = float(self.config.params.get("break_tolerance", 0.0008))
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0005))

        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        recent = entry_candles[-max(lookback + 3, 20):]
        last = recent[-1]

        levels_sorted = sorted(levels, key=lambda x: x.strength, reverse=True)

        for lvl in levels_sorted:
            if lvl.level <= 0:
                continue

            # Bullish role reversal: resistance broken, now acting as support
            if lvl.kind == "resistance":
                # Find a breakout close above
                broke = any(c.close > lvl.upper * (1 + break_tol) for c in recent[-lookback:])
                if not broke:
                    continue

                # Retest: last candle touches the zone and closes above it
                touched = is_candle_touching_level(last, lvl.upper, touch_tol) or is_candle_touching_level(last, lvl.level, touch_tol)
                holds = last.close >= lvl.upper
                if touched and holds:
                    entry = last.close
                    sl = lvl.lower * (1 - sl_buffer)
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
                        strength=0.68,
                        timeframe=tf,
                        reasons=[
                            "SR_ROLE_REVERSAL",
                            f"RES_TO_SUP|{lvl.level:.5f}",
                        ],
                        meta={"level": lvl.level, "zone_lower": lvl.lower, "zone_upper": lvl.upper},
                    )

            # Bearish role reversal: support broken, now acting as resistance
            if lvl.kind == "support":
                broke = any(c.close < lvl.lower * (1 - break_tol) for c in recent[-lookback:])
                if not broke:
                    continue

                touched = is_candle_touching_level(last, lvl.lower, touch_tol) or is_candle_touching_level(last, lvl.level, touch_tol)
                holds = last.close <= lvl.lower
                if touched and holds:
                    entry = last.close
                    sl = lvl.upper * (1 + sl_buffer)
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
                        strength=0.68,
                        timeframe=tf,
                        reasons=[
                            "SR_ROLE_REVERSAL",
                            f"SUP_TO_RES|{lvl.level:.5f}",
                        ],
                        meta={"level": lvl.level, "zone_lower": lvl.lower, "zone_upper": lvl.upper},
                    )

        return None
