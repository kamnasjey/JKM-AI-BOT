# analyzer.py
"""
Ганбаярын multi-timeframe анализын simple v2.

D1, H4, H1, M15 дээр үнэ хаашаа чиглэж байгаа,
хаана support/resistance байгаа, одоогийн үнэ ямар байршилд байна гэх мэт
ерөнхий дүгнэлтийг Монгол хэлээр буцаана.

Гол public функц:
    analyze_pair_multi_tf_v2(pair) -> str
"""

from __future__ import annotations
from typing import List, Dict, Any
from datetime import datetime

from market_data_cache import market_cache


def _parse_time(iso_str: str) -> datetime:
    try:
        return datetime.fromisoformat(iso_str.replace("Z", ""))
    except Exception:
        return datetime.utcnow()


def _simple_trend(candles: List[Dict[str, Any]]) -> str:
    """
    Энгийн trend:
      - Сүүлийн хаалт N лааны өмнөх хаалтаас өндөр -> up
      - Доогуур -> down
      - бусад -> flat
    """
    if len(candles) < 10:
        return "unknown"
    closes = [c["close"] for c in candles]
    if closes[-1] > closes[-10]:
        return "up"
    elif closes[-1] < closes[-10]:
        return "down"
    return "flat"


def _key_levels(candles: List[Dict[str, Any]]) -> Dict[str, float]:
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    if not closes:
        return {"support": 0.0, "resistance": 0.0}
    return {
        "support": min(lows[-50:]) if len(lows) >= 50 else min(lows),
        "resistance": max(highs[-50:]) if len(highs) >= 50 else max(highs),
        "last_close": closes[-1],
    }


def _trend_to_mn(t: str) -> str:
    if t == "up":
        return "өсөх (uptrend)"
    if t == "down":
        return "унаж буй (downtrend)"
    if t == "flat":
        return "хажуу (range / flat)"
    return "тодорхойгүй"


def analyze_pair_multi_tf_v2(pair: str) -> str:
    """Use in-memory market cache to analyze D1/H4/H1/M15 trends.

    Assumes the background ingestor is keeping `market_cache` warm with M5 candles.
    """
    p = str(pair or "").strip().upper().replace("/", "").replace(" ", "")
    if not p:
        return "⚠ Pair хоосон байна."

    d1 = market_cache.get_resampled(p, "D1")
    h4 = market_cache.get_resampled(p, "H4")
    h1 = market_cache.get_resampled(p, "H1")
    m15 = market_cache.get_resampled(p, "M15")

    if not d1 or not h4 or not h1 or not m15:
        return f"⚠ {p} дээр хангалттай өгөгдөл cache-д алга байна. (Ingestor ажиллаж байгаа эсэхийг шалга)"

    d1_trend = _simple_trend(d1)
    h4_trend = _simple_trend(h4)
    h1_trend = _simple_trend(h1)
    m15_trend = _simple_trend(m15)

    d1_levels = _key_levels(d1)
    h4_levels = _key_levels(h4)

    last_price = m15[-1]["close"]
    d1_s = d1_levels["support"]
    d1_r = d1_levels["resistance"]

    # RR / trade idea simple:
    bias = "NO TRADE"
    reason = []

    # Хандлага нийлсэн эсэх
    if d1_trend == h4_trend == "up":
        bias = "BUY SIDE ONLY"
        reason.append("D1 ба H4 дээр хоёул өсөх хандлагатай.")
    elif d1_trend == h4_trend == "down":
        bias = "SELL SIDE ONLY"
        reason.append("D1 ба H4 дээр хоёул унах хандлагатай.")
    else:
        bias = "NEUTRAL / RANGE"
        reason.append("D1 ба H4 чиглэл зөрчилтэй эсвэл тодорхойгүй байна.")

    # Үнэ хаана байна?
    if last_price <= d1_s:
        reason.append("Одоогийн үнэ том support бүс орчимд байна (D1 support).")
    elif last_price >= d1_r:
        reason.append("Одоогийн үнэ том resistance бүс орчимд байна (D1 resistance).")
    else:
        mid = (d1_s + d1_r) / 2
        if last_price < mid:
            reason.append("Үнэ дунд түвшнээс доош хэсэгт байна.")
        else:
            reason.append("Үнэ дунд түвшнээс дээш хэсэгт байна.")

    text = []
    text.append("📊 <b>ГАНБАЯР MULTI-TF ANALYZER (v2)</b>")
    text.append(f"Хос: <b>{p}</b>")
    text.append("")
    text.append("🕒 <b>D1</b>")
    text.append(f"  - Хандлага: {d1_trend} ({_trend_to_mn(d1_trend)})")
    text.append(f"  - Support: {d1_s:.3f}")
    text.append(f"  - Resistance: {d1_r:.3f}")
    text.append("")
    text.append("🕒 <b>H4</b>")
    text.append(f"  - Хандлага: {h4_trend} ({_trend_to_mn(h4_trend)})")
    text.append("")
    text.append("🕒 <b>H1</b>")
    text.append(f"  - Хандлага: {h1_trend} ({_trend_to_mn(h1_trend)})")
    text.append("")
    text.append("🕒 <b>M15</b>")
    text.append(f"  - Хандлага: {m15_trend} ({_trend_to_mn(m15_trend)})")
    text.append(f"  - Сүүлийн үнэ: {last_price:.3f}")
    text.append("")
    text.append(f"🎯 <b>Үндсэн дүгнэлт:</b> {bias}")
    if reason:
        text.append("📝 <b>Шалтгаанууд:</b>")
        for r in reason:
            text.append(f"  • {r}")


    return "\n".join(text)


def analyze_pair_multi_tf(pair: str) -> str:
    return analyze_pair_multi_tf_v2(pair)


# --- New Structured Analyzer ---
def get_setup_v2(pair: str) -> Dict[str, Any]:
    """
    Simulated structured output for Autopilot V1.
    In real V1, this should use `engine_blocks` to calculate precise entry/sl/tp.
    For now, we derive some basic logic similar to text logic but return dict.
    """
    p = str(pair or "").strip().upper().replace("/", "").replace(" ", "")
    if not p:
        return {}

    d1 = market_cache.get_resampled(p, "D1")
    h4 = market_cache.get_resampled(p, "H4")

    if not d1 or not h4:
        return {}

    # Simple reuse of internal helpers
    # Hack to reuse existing parsed time logic if needed, but get_candles returns dicts
    # We can just check trends
    d1_trend = _simple_trend(d1)
    h4_trend = _simple_trend(h4)
    m15 = market_cache.get_resampled(p, "M15")
    if not m15:
        return {}
    last_price = m15[-1]["close"]
    
    setup = {}
    
    # Very basic simulation of a strategy to test notificatons
    # Valid setup ONLY if D1 Up + H4 Up -> BUY, or D1 Down + H4 Down -> SELL
    if d1_trend == "up" and h4_trend == "up":
        setup = {
            "pair": p,
            "direction": "BUY",
            "timeframe": "M15",
            "entry": last_price,
            "sl": last_price * 0.995,  # 0.5% SL
            "tp": last_price * 1.01,   # 1% TP
            "rr": 2.0,
            "reasons": ["D1 Uptrend", "H4 Uptrend", "Trend Alignment"]
        }
    elif d1_trend == "down" and h4_trend == "down":
        setup = {
            "pair": p,
            "direction": "SELL",
            "timeframe": "M15",
            "entry": last_price,
            "sl": last_price * 1.005,
            "tp": last_price * 0.99,
            "rr": 2.0,
            "reasons": ["D1 Downtrend", "H4 Downtrend", "Trend Alignment"]
        }
    
    return setup

