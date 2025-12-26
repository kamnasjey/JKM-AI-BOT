# strategy.py
"""
JKM-trading-bot-ийн simple авто scan стратеги.

Идея:
  - IG-ийн өгөгдлөөс M5 (эсвэл config.AAUTO_TIMEFRAME) лаануудыг авах
  - MA(50) ашиглан тренд тодорхойлох
  - Сүүлийн 3 лаанд MA-г дагаж чиглэл авсан эсэхээр simple BUY/SELL setup гаргах
  - RR≈1:3 болгон SL/TP тооцоолох

Гарч ирсэн setup-уудыг telegram_bot.py авто scan болон гар аргаар scan дээр ашиглана.
"""

from __future__ import annotations
import os
from datetime import datetime
from typing import List, Dict, Any, Optional, TypedDict
from dataclasses import dataclass

from ig_client import IGClient
from engine_blocks import (
    normalize_candles,
    sma,
    Candle,
)


@dataclass
class SimpleStrategyResult:
    pair: str
    timeframe: str
    direction: str
    entry: float
    sl: float
    tp: float
    ma: float
    # visualization-д хэрэг болдог тул
    # raw dict хэлбэрээр буцааж болно, эсвэл Candle obj
    candles: List[Dict[str, Any]]


def _get_epic_for_pair(pair: str) -> Optional[str]:
    key = f"EPIC_{pair.replace('/', '')}"
    epic = os.getenv(key, "").strip()
    return epic or None


def _map_tf_to_resolution(tf: str) -> str:
    tf = (tf or "").upper().replace(" ", "")
    mapping = {
        "M1": "MINUTE",
        "M5": "MINUTE_5",
        "M15": "MINUTE_15",
        "M30": "MINUTE_30",
        "H1": "HOUR",
        "H4": "HOUR_4",
        "D1": "DAY",
    }
    return mapping.get(tf, "MINUTE_5")


def scan_pairs(
    timeframe: str,
    limit: int,
    pairs: List[str],
) -> List[Dict[str, Any]]:
    """
    Өгөгдсөн timeframe дээр өгөгдсөн pairs жагсаалтад simple setup хайна.
    Legacy compatibility: Returns List[Dict] to match old interface for now.
    """

    is_demo_env = os.getenv("IG_IS_DEMO", "false").lower() in ("1", "true", "yes")
    ig = IGClient.from_env(is_demo=is_demo_env)

    results: List[Dict[str, Any]] = []

    for pair in pairs:
        epic = _get_epic_for_pair(pair)
        if not epic:
            continue

        res = _map_tf_to_resolution(timeframe)
        try:
            raw = ig.get_candles(epic, res, max_points=limit)
        except Exception:
            continue

        if len(raw) < 60:
            continue

        # Use engine_blocks to normalize
        # Note: IGClient raw candles might need robust parsing inside normalize_candles
        # raw is List[Dict]
        
        # We handle time parsing manually here to preserve legacy structure for 'candles' key
        # but use engine blocks for math.
        
        # 1. Parse for internal math (Candle objects)
        eng_candles = normalize_candles(raw)
        closes = [c.close for c in eng_candles]
        lows = [c.low for c in eng_candles]
        highs = [c.high for c in eng_candles]
        
        # 2. Compute MA
        ma_period = 50
        ma_series = sma(closes, ma_period)
        
        if len(ma_series) < 3:
            continue

        # Logic
        last_close = closes[-1]
        prev_close = closes[-2]
        last_ma = ma_series[-1]
        prev_ma = ma_series[-2]

        direction: Optional[str] = None

        if prev_close < prev_ma and last_close > last_ma:
            direction = "BUY"
        elif prev_close > prev_ma and last_close < last_ma:
            direction = "SELL"

        if direction is None:
            continue

        # Simple SL/TP
        if direction == "BUY":
            # SL = lowest of last 5
            sl = min(lows[-5:])
            risk = last_close - sl
            if risk <= 0:
                continue
            tp = last_close + risk * 3.0
        else:
            # SL = highest of last 5
            sl = max(highs[-5:])
            risk = sl - last_close
            if risk <= 0:
                continue
            tp = last_close - risk * 3.0

        setup = {
            "direction": direction,
            "entry": round(last_close, 5),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "ma": round(last_ma, 5),
        }
        
        # Re-construct raw candles with parsed time for frontend/bot
        # (Legacy behavior expected dicts)
        out_candles = []
        for c in eng_candles:
             out_candles.append({
                 "time": c.time,
                 "open": c.open,
                 "high": c.high,
                 "low": c.low,
                 "close": c.close
             })

        results.append(
            {
                "pair": pair,
                "timeframe": timeframe,
                "setup": setup,
                "candles": out_candles,
            }
        )

    return results
