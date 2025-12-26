"""price_momentum_weakening.py

Priority C: PRICE_MOMENTUM_WEAKENING

This is a *warning* detector, not a tradable setup generator.
It emits an annotation (DetectorSignal.kind == "annotation") when recent
price momentum appears to be weakening.

Heuristic (price-only):
- Compare last N-candle net move vs previous N-candle net move
- If net move shrinks while still pushing in same direction, warn
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle, compute_atr

from .base import BaseDetector, DetectorSignal


class PriceMomentumWeakeningDetector(BaseDetector):
    name = "price_momentum_weakening"

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

        win = int(self.config.params.get("window", 20))
        ratio_thresh = float(self.config.params.get("ratio_threshold", 0.55))

        if len(entry_candles) < win * 2 + 5:
            return None

        # Use close-to-close net move
        prev_seg = entry_candles[-(2 * win + 1):-(win + 1)]
        last_seg = entry_candles[-(win + 1):]

        prev_move = prev_seg[-1].close - prev_seg[0].close
        last_move = last_seg[-1].close - last_seg[0].close

        # Only warn if both segments move in same direction but latest is weaker
        if prev_move == 0:
            return None

        if (prev_move > 0 and last_move > 0) or (prev_move < 0 and last_move < 0):
            if abs(last_move) <= abs(prev_move) * ratio_thresh:
                atr = compute_atr(entry_candles[-60:], period=14)
                reasons = [
                    f"MOMENTUM_WEAKENING|prev={prev_move:.6f}|last={last_move:.6f}|atr={atr:.6f}",
                ]

                # Annotation object
                return DetectorSignal(
                    detector_name=self.name,
                    pair=pair,
                    direction="BUY" if last_move > 0 else "SELL",
                    entry=entry_candles[-1].close,
                    sl=entry_candles[-1].close,
                    tp=entry_candles[-1].close,
                    rr=0.0,
                    kind="annotation",
                    strength=0.0,
                    timeframe=str(user_config.get("entry_tf", "M15")).upper(),
                    reasons=reasons,
                    meta={"prev_move": prev_move, "last_move": last_move, "window": win},
                )

        return None
