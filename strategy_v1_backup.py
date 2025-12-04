# strategy.py
"""
Энд Ганбаярын арилжааны АРГА БАРИЛ (стратеги) тусдаа байдаг.
Цаашид стратегиа өөрчлөхдөө зөвхөн энэ файлыг засахад болно.
"""

from typing import Any, Dict, List

from analyzer import detect_trend, find_key_levels
from rr_filter import check_rr


def analyze_xauusd_h1_m15(h1_candles: List[Dict[str, Any]],
                          m15_candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    XAUUSD pair дээр:
      - H1 = гол чиглэл + түвшин
      - M15 = entry/SL/TP хайх
    дээр ажилладаг Ганбаярын одоогийн стратеги.

    Буцаах бүтэц (dict):
      - status: "no_data" | "no_trade" | "no_trade_rr" | "trade"
      - дээрээс нь нэмэлт мэдээллүүд (trend, levels, entry, sl, tp, rr, г.м)
    """

    if not h1_candles or not m15_candles:
        return {
            "status": "no_data",
            "reason": "h1 эсвэл m15 candles хоосон байна",
        }

    # ---------------- H1 анализ ----------------
    h1_trend = detect_trend(h1_candles)
    h1_levels = find_key_levels(h1_candles)

    result_base: Dict[str, Any] = {
        "pair": "XAUUSD",
        "h1_trend": h1_trend,
        "h1_levels": h1_levels,
        "entry_tf": "M15",
    }

    # Одоогийн хувилбар: зөвхөн uptrend үед BUY хайна
    if h1_trend != "up":
        # Хэрвээ дараа нь SELL логик нэмэх бол эндээс салгаж бичнэ
        return {
            **result_base,
            "status": "no_trade",
            "reason": "H1 uptrend биш тул BUY setup хайхгүй.",
        }

    # ---------------- M15 анализ (entry) ----------------
    last_m15 = m15_candles[-1]

    entry = last_m15["close"]
    sl = last_m15["low"] - 2.0  # SL buffer = 2 пункт (config болгож салгаж болно)

    logical_tps = [
        h1_levels["resistance"],
        h1_levels["resistance"] + 5,
        h1_levels["resistance"] + 10,
    ]

    rr_result = check_rr(entry, sl, logical_tps)

    if not rr_result:
        return {
            **result_base,
            "status": "no_trade_rr",
            "reason": "R:R ≥ 1:3 хангах TP олдсонгүй.",
            "entry": entry,
            "sl": sl,
            "logical_tps": logical_tps,
        }

    # R:R OK → боломжит trade
    tp = rr_result["tp"]
    rr = rr_result["rr"]

    return {
        **result_base,
        "status": "trade",
        "direction": "BUY",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "logical_tps": logical_tps,
    }
