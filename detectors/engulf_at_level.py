"""engulf_at_level.py

Detects engulfing candles occurring at key levels (S/R or Fib).

Priority A: ENGULF_AT_LEVEL
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle, detect_multi_candle_patterns

from .base import BaseDetector, DetectorSignal
from .utils import build_tp, entry_tf_from_profile, is_candle_touching_level, min_rr_from_profile


class EngulfAtLevelDetector(BaseDetector):
    name = "engulf_at_level"

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

        if len(entry_candles) < 4:
            return None

        patterns = detect_multi_candle_patterns(entry_candles[-3:])
        if not patterns:
            return None

        last = entry_candles[-1]
        prev = entry_candles[-2]

        # Find engulfing
        bull = any(p.pattern == "bullish_engulfing" for p in patterns)
        bear = any(p.pattern == "bearish_engulfing" for p in patterns)
        if not bull and not bear:
            return None

        tol = float(self.config.params.get("level_tolerance", 0.0015))
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0004))

        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        # Key levels: clustered S/R zones + fib retrace values
        key_levels: List[float] = []
        if primitives.sr_zones_clustered:
            for z in primitives.sr_zones_clustered[:10]:
                key_levels.append(z.level)
                key_levels.append(z.lower)
                key_levels.append(z.upper)
        else:
            key_levels.extend([primitives.sr_zones.support, primitives.sr_zones.resistance])

        if primitives.fib_levels and primitives.fib_levels.retrace:
            key_levels.extend(primitives.fib_levels.retrace.values())

        key_levels = [x for x in key_levels if isinstance(x, (int, float)) and x > 0]
        if not key_levels:
            return None

        # Must occur at/near a key level: wick touches a level
        at_level = any(is_candle_touching_level(last, lvl, tol) or is_candle_touching_level(prev, lvl, tol) for lvl in key_levels)
        if not at_level:
            return None

        if bull:
            entry = last.close
            sl = min(prev.low, last.low) * (1 - sl_buffer)
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
                strength=0.7,
                timeframe=tf,
                reasons=["ENGULF_AT_LEVEL", "BULLISH_ENGULF"],
                meta={"pattern": "bullish_engulfing"},
            )

        if bear:
            entry = last.close
            sl = max(prev.high, last.high) * (1 + sl_buffer)
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
                strength=0.7,
                timeframe=tf,
                reasons=["ENGULF_AT_LEVEL", "BEARISH_ENGULF"],
                meta={"pattern": "bearish_engulfing"},
            )

        return None
