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
from typing import List, Dict, Any, Optional
from datetime import datetime

import os

from ig_client import IGClient


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


def _get_epic_for_pair(pair: str) -> Optional[str]:
    key = f"EPIC_{pair.replace('/', '')}"
    epic = os.getenv(key, "").strip()
    return epic or None


def _sma(values: List[float], period: int) -> List[float]:
    if period <= 0 or len(values) < period:
        return [0.0] * len(values)
    out: List[float] = []
    s = sum(values[:period])
    out.extend([0.0] * (period - 1))
    out.append(s / period)
    for i in range(period, len(values)):
        s += values[i] - values[i - period]
        out.append(s / period)
    return out


def scan_pairs(
    timeframe: str,
    limit: int,
    pairs: List[str],
) -> List[Dict[str, Any]]:
    """
    Өгөгдсөн timeframe дээр өгөгдсөн pairs жагсаалтад simple setup хайна.
    Буцаах формат:
      [{
        "pair": str,
        "timeframe": str,
        "setup": {"direction","entry","sl","tp","ma"},
        "candles": [{time,open,high,low,close}, ...]
      }, ...]
    """

    is_demo_env = os.getenv("IG_IS_DEMO", "false").lower() in ("1", "true", "yes")
    ig = IGClient.from_env(is_demo=is_demo_env)

    results: List[Dict[str, Any]] = []

    for pair in pairs:
        epic = _get_epic_for_pair(pair)
        if not epic:
            continue

        res = _map_tf_to_resolution(timeframe)
        raw = ig.get_candles(epic, res, max_points=limit)
        if len(raw) < 60:
            continue

        # time parse
        candles: List[Dict[str, Any]] = []
        closes: List[float] = []
        lows: List[float] = []
        highs: List[float] = []
        for c in raw[-limit:]:
            try:
                t = datetime.fromisoformat(c["time"].replace("Z", ""))
            except Exception:
                t = datetime.utcnow()
            candles.append(
                {
                    "time": t,
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                }
            )
            closes.append(float(c["close"]))
            lows.append(float(c["low"]))
            highs.append(float(c["high"]))

        ma_period = 50
        ma = _sma(closes, ma_period)
        if len(ma) != len(closes):
            continue

        # Сүүлийн 3 лаан дээр simple логик – диагональ MA-г дагаж хөдөлж байгаа эсэх
        last_close = closes[-1]
        prev_close = closes[-2]
        last_ma = ma[-1]
        prev_ma = ma[-2]

        direction: Optional[str] = None

        if prev_close < prev_ma and last_close > last_ma:
            direction = "BUY"
        elif prev_close > prev_ma and last_close < last_ma:
            direction = "SELL"

        if direction is None:
            # Энэ pair дээр тодорхой сигнал гарсангүй
            continue

        # Simple SL/TP – ойролцоогоор 1:3 RR
        if direction == "BUY":
            sl = min(lows[-5:])
            risk = last_close - sl
            if risk <= 0:
                continue
            tp = last_close + risk * 3.0
        else:
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

        results.append(
            {
                "pair": pair,
                "timeframe": timeframe,
                "setup": setup,
                "candles": candles,
            }
        )

    return results
