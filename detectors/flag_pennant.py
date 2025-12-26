"""flag_pennant.py

Detects a simple flag/pennant continuation breakout.

Priority B: FLAG_PENNANT

Heuristic:
- Identify an impulse move over a window (price change > threshold)
- Consolidation: subsequent candles have smaller range and drift sideways
- Breakout: last close breaks consolidation high/low in impulse direction

This is intentionally conservative and avoids heavy pattern fitting.
"""

from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Optional

from engine_blocks import Candle, compute_atr

from .base import BaseDetector, DetectorSignal
from .utils import build_tp, entry_tf_from_profile, min_rr_from_profile


class FlagPennantDetector(BaseDetector):
    name = "flag_pennant"

    def detect(
        self,
        pair: str,
        entry_candles: List[Candle],
        trend_candles: List[Candle],
        primitives: Any,
        user_config: Dict[str, Any],
    ) -> Optional[DetectorSignal]:
        if len(entry_candles) < 80:
            return None

        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        impulse_len = int(self.config.params.get("impulse_len", 20))
        cons_len = int(self.config.params.get("consolidation_len", 18))
        impulse_atr_mul = float(self.config.params.get("impulse_atr_mul", 2.0))
        breakout_tol = float(self.config.params.get("break_tolerance", 0.0006))

        segment = entry_candles[-(impulse_len + cons_len + 5):]
        impulse = segment[:impulse_len]
        cons = segment[impulse_len:impulse_len + cons_len]

        if len(impulse) < impulse_len or len(cons) < cons_len:
            return None

        atr = compute_atr(entry_candles[-60:], period=14)
        if atr <= 0:
            return None

        impulse_move = impulse[-1].close - impulse[0].open
        if abs(impulse_move) < atr * impulse_atr_mul:
            return None

        direction = "BUY" if impulse_move > 0 else "SELL"

        # Consolidation should be lower volatility than impulse
        impulse_ranges = [c.high - c.low for c in impulse]
        cons_ranges = [c.high - c.low for c in cons]
        if mean(cons_ranges) > mean(impulse_ranges) * 0.8:
            return None

        cons_high = max(c.high for c in cons)
        cons_low = min(c.low for c in cons)

        last = entry_candles[-1]
        prev = entry_candles[-2]

        if direction == "BUY":
            if last.close > cons_high * (1 + breakout_tol) and prev.close <= cons_high:
                entry = last.close
                sl = cons_low
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
                    strength=0.64,
                    timeframe=tf,
                    reasons=["FLAG_PENNANT", "BREAK_UP"],
                    meta={"cons_high": cons_high, "cons_low": cons_low},
                )

        else:
            if last.close < cons_low * (1 - breakout_tol) and prev.close >= cons_low:
                entry = last.close
                sl = cons_high
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
                    strength=0.64,
                    timeframe=tf,
                    reasons=["FLAG_PENNANT", "BREAK_DOWN"],
                    meta={"cons_high": cons_high, "cons_low": cons_low},
                )

        return None
