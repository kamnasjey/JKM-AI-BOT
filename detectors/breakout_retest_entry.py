"""breakout_retest_entry.py

Detects breakout -> retest -> confirmation entry.

Priority A: BREAKOUT_RETEST_ENTRY

This is intentionally more strict than the legacy break_retest detector.
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


class BreakoutRetestEntryDetector(BaseDetector):
    name = "breakout_retest_entry"

    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        if len(entry_candles) < 35:
            return None

        levels = _levels_from_primitives(primitives)
        if not levels:
            return None

        lookback = int(self.config.params.get("lookback", 25))
        break_tol = float(self.config.params.get("break_tolerance", 0.0008))
        retest_tol = float(self.config.params.get("retest_tolerance", 0.0012))
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0005))

        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        segment = entry_candles[-lookback:]
        last = segment[-1]

        levels_sorted = sorted(levels, key=lambda x: x.strength, reverse=True)

        for lvl in levels_sorted:
            if lvl.level <= 0:
                continue

            # Bullish: breakout above resistance, retest, then confirmation close above
            if lvl.kind == "resistance":
                breakout_idx = None
                for i in range(2, len(segment) - 2):
                    if segment[i - 1].close <= lvl.upper and segment[i].close > lvl.upper * (1 + break_tol):
                        breakout_idx = i
                        break
                if breakout_idx is None:
                    continue

                retest_idx = None
                for j in range(breakout_idx + 1, len(segment) - 1):
                    if is_candle_touching_level(segment[j], lvl.upper, retest_tol):
                        # retest should not close back below the zone
                        if segment[j].close >= lvl.lower:
                            retest_idx = j
                            break
                if retest_idx is None:
                    continue

                # Confirmation: last candle closes above the zone
                if last.close >= lvl.upper:
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
                        strength=0.72,
                        timeframe=tf,
                        reasons=[
                            "BREAKOUT_RETEST_ENTRY",
                            f"LEVEL|{lvl.level:.5f}",
                        ],
                        meta={"level": lvl.level, "zone_lower": lvl.lower, "zone_upper": lvl.upper},
                    )

            # Bearish: breakout below support, retest, then confirmation close below
            if lvl.kind == "support":
                breakout_idx = None
                for i in range(2, len(segment) - 2):
                    if segment[i - 1].close >= lvl.lower and segment[i].close < lvl.lower * (1 - break_tol):
                        breakout_idx = i
                        break
                if breakout_idx is None:
                    continue

                retest_idx = None
                for j in range(breakout_idx + 1, len(segment) - 1):
                    if is_candle_touching_level(segment[j], lvl.lower, retest_tol):
                        if segment[j].close <= lvl.upper:
                            retest_idx = j
                            break
                if retest_idx is None:
                    continue

                if last.close <= lvl.lower:
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
                        strength=0.72,
                        timeframe=tf,
                        reasons=[
                            "BREAKOUT_RETEST_ENTRY",
                            f"LEVEL|{lvl.level:.5f}",
                        ],
                        meta={"level": lvl.level, "zone_lower": lvl.lower, "zone_upper": lvl.upper},
                    )

        return None
