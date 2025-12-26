"""fibo_retrace_confluence.py

Detects fib retracement entries with confluence (near S/R zone).

Priority A: FIBO_RETRACE_CONFLUENCE (+ extension targets)

Heuristic (conservative):
- Requires a valid swing and fib retrace map
- Price near configured fib retrace level(s)
- Also near a clustered S/R level (support in uptrend, resistance in downtrend)
- TP prefers fib extension (1.618, 1.272) when available
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from engine_blocks import Candle

from .base import BaseDetector, DetectorSignal
from .utils import build_tp, entry_tf_from_profile, is_near_level_price, min_rr_from_profile


class FiboRetraceConfluenceDetector(BaseDetector):
    name = "fibo_retrace_confluence"

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

        if len(entry_candles) < 30:
            return None

        if primitives.swing.swing is None or not primitives.swing.found:
            return None

        fib = primitives.fib_levels
        if not fib.retrace:
            return None

        last = entry_candles[-1]
        price = last.close

        blocks = user_config.get("blocks", {}) if isinstance(user_config.get("blocks", {}), dict) else {}
        fibo_cfg = blocks.get("fibo", {}) if isinstance(blocks.get("fibo", {}), dict) else {}

        # Retrace levels to check (defaults aligned with existing fib strategy)
        levels = fibo_cfg.get("levels", [0.5, 0.618])
        try:
            levels = [float(x) for x in levels]
        except Exception:
            levels = [0.5, 0.618]

        tol = float(self.config.params.get("level_tolerance", 0.0015))
        sl_buffer = float(self.config.params.get("sl_buffer", 0.0004))

        # Determine trend direction for role of S/R
        trend_dir = primitives.trend_structure.direction
        if primitives.structure_trend and primitives.structure_trend.structure_valid:
            trend_dir = primitives.structure_trend.direction

        if trend_dir not in ("up", "down"):
            return None

        # Find if price is near any chosen fib retrace level
        fib_hit = None
        for lvl in levels:
            lvl_price = fib.retrace.get(lvl)
            if lvl_price and is_near_level_price(price, lvl_price, tol):
                fib_hit = (lvl, lvl_price)
                break

        if fib_hit is None:
            return None

        # Confluence with S/R clustered zones
        sr_ok = False
        sr_level = None
        if primitives.sr_zones_clustered:
            if trend_dir == "up":
                for z in primitives.sr_zones_clustered[:10]:
                    if not z.is_resistance and is_near_level_price(price, z.level, tol):
                        sr_ok = True
                        sr_level = z.level
                        break
            else:
                for z in primitives.sr_zones_clustered[:10]:
                    if z.is_resistance and is_near_level_price(price, z.level, tol):
                        sr_ok = True
                        sr_level = z.level
                        break
        else:
            # Fallback: basic S/R
            sr = primitives.sr_zones
            if trend_dir == "up" and sr.support and is_near_level_price(price, sr.support, tol):
                sr_ok = True
                sr_level = sr.support
            if trend_dir == "down" and sr.resistance and is_near_level_price(price, sr.resistance, tol):
                sr_ok = True
                sr_level = sr.resistance

        if not sr_ok:
            return None

        min_rr = min_rr_from_profile(user_config, default=2.0)
        tf = entry_tf_from_profile(user_config)

        swing = primitives.swing.swing

        if trend_dir == "up":
            direction = "BUY"
            entry = price
            sl = swing.low * (1 - sl_buffer)

            # Prefer extension target
            tp = None
            for ext in (1.618, 1.272, 2.0):
                if ext in fib.extensions:
                    cand_tp = fib.extensions[ext]
                    if cand_tp and cand_tp > entry:
                        tp = cand_tp
                        break
            if tp is None:
                tp = build_tp(entry, sl, direction, min_rr)
            if tp is None:
                return None

            # compute rr from actual tp
            rr = abs(tp - entry) / max(abs(entry - sl), 1e-9)

            if rr < min_rr:
                return None

            return DetectorSignal(
                detector_name=self.name,
                pair=pair,
                direction=direction,
                entry=entry,
                sl=sl,
                tp=tp,
                rr=rr,
                strength=0.78,
                timeframe=tf,
                reasons=[
                    "FIBO_RETRACE_CONFLUENCE",
                    f"FIB|{fib_hit[0]}@{fib_hit[1]:.5f}",
                    f"SR|{sr_level:.5f}" if sr_level else "SR",
                    f"TP_EXT" if tp in fib.extensions.values() else "TP_RR",
                ],
                meta={
                    "trend_dir": trend_dir,
                    "fibo_level": fib_hit[0],
                    "fibo_price": fib_hit[1],
                    "sr_level": sr_level,
                },
            )

        # down
        direction = "SELL"
        entry = price
        sl = swing.high * (1 + sl_buffer)

        tp = None
        for ext in (1.618, 1.272, 2.0):
            if ext in fib.extensions:
                cand_tp = fib.extensions[ext]
                if cand_tp and cand_tp < entry:
                    tp = cand_tp
                    break
        if tp is None:
            tp = build_tp(entry, sl, direction, min_rr)
        if tp is None:
            return None

        rr = abs(tp - entry) / max(abs(sl - entry), 1e-9)
        if rr < min_rr:
            return None

        return DetectorSignal(
            detector_name=self.name,
            pair=pair,
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            rr=rr,
            strength=0.78,
            timeframe=tf,
            reasons=[
                "FIBO_RETRACE_CONFLUENCE",
                f"FIB|{fib_hit[0]}@{fib_hit[1]:.5f}",
                f"SR|{sr_level:.5f}" if sr_level else "SR",
                f"TP_EXT" if tp in fib.extensions.values() else "TP_RR",
            ],
            meta={
                "trend_dir": trend_dir,
                "fibo_level": fib_hit[0],
                "fibo_price": fib_hit[1],
                "sr_level": sr_level,
            },
        )
