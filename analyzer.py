"""
analyzer.py
Ганбаярын multi-timeframe (D1, H4, H1, M15) анализыг IGMarket-ийн candlestick өгөгдлөөр хийж,
entry / SL / TP болон R:R-ийг тооцоолж, Монгол тайлбар текст буцаана.

Гол public функцүүд:
- analyze_pair_multi_tf_ig_v2(ig, epic, pair)
- analyze_pair_multi_tf_ig(ig, epic, pair)  # v2-ийн alias
"""

from typing import List, Dict, Tuple


# -------------------------------------------------------------------
# ТУСЛАХ ФУНКЦУУД
# -------------------------------------------------------------------


def _detect_trend(candles: List[Dict], lookback: int = 40) -> str:
    """
    Жижигхэн энгийн trend тодорхойлно:
    - сүүлийн N свечийн эхний close-оос сүүлийн close мэдэгдэхүйц их байвал -> up
    - мэдэгдэхүйц бага байвал -> down
    - бусад үед -> range
    """
    if len(candles) < 5:
        return "range"

    window = candles[-lookback:] if len(candles) > lookback else candles[:]
    closes = [c["close"] for c in window]

    first = closes[0]
    last = closes[-1]

    # хувь өөрчлөлт (0.3% босго)
    if first == 0:
        return "range"

    change = (last - first) / abs(first)

    if change > 0.003:
        return "up"
    elif change < -0.003:
        return "down"
    else:
        return "range"


def _detect_levels(candles: List[Dict], lookback: int = 80) -> Dict[str, float]:
    """
    Сүүлийн lookback свечид хамгийн өндөр high, хамгийн доод low-г авч
    support / resistance гэж тодорхойлно.
    """
    if not candles:
        return {"support": 0.0, "resistance": 0.0}

    window = candles[-lookback:] if len(candles) > lookback else candles[:]

    lows = [c["low"] for c in window]
    highs = [c["high"] for c in window]

    support = min(lows)
    resistance = max(highs)

    return {
        "support": round(support, 2),
        "resistance": round(resistance, 2),
    }


def _choose_direction(d1_trend: str, h4_trend: str) -> str:
    """
    D1 ба H4 чиглэлийг харж ерөнхий чиглэл сонгоно.
    """
    if d1_trend == "up" and h4_trend == "up":
        return "buy"
    if d1_trend == "down" and h4_trend == "down":
        return "sell"
    return "none"


def _prepare_entry_sl_tp(
    direction: str,
    m15_candles: List[Dict],
    h4_levels: Dict[str, float],
) -> Tuple[bool, Dict[str, float], float]:
    """
    Entry / SL / TP сонгож, R:R тооцоолно.

    return:
        (has_setup, result_dict, rr_value)

    result_dict:
        {
            "entry": float,
            "sl": float,
            "tp": float
        }
    """
    if not m15_candles:
        return False, {}, 0.0

    last = m15_candles[-1]
    entry = float(last["close"])
    last_high = float(last["high"])
    last_low = float(last["low"])

    # Жижиг buffer – свечийн өндрийн тал орчим
    candle_range = max(last_high - last_low, 0.0001)
    buffer = candle_range * 0.5

    if direction == "buy":
        sl = last_low - buffer
        tp = float(h4_levels["resistance"])  # дээш зорилго

        risk = entry - sl
        reward = tp - entry

        if risk <= 0 or reward <= 0:
            return False, {}, 0.0

        rr = reward / risk

        if rr < 3.0:
            # Хэрэв H4 resistance хэт ойрхон байвал жаахан сунгаж үзэж болно
            extra = candle_range * 3
            tp_alt = tp + extra
            reward_alt = tp_alt - entry
            if reward_alt > 0:
                rr_alt = reward_alt / risk
                if rr_alt >= 3.0:
                    return True, {
                        "entry": round(entry, 3),
                        "sl": round(sl, 3),
                        "tp": round(tp_alt, 3),
                    }, rr_alt
            return False, {}, rr
        else:
            return True, {
                "entry": round(entry, 3),
                "sl": round(sl, 3),
                "tp": round(tp, 3),
            }, rr

    elif direction == "sell":
        sl = last_high + buffer
        tp = float(h4_levels["support"])  # доош зорилго

        risk = sl - entry
        reward = entry - tp

        if risk <= 0 or reward <= 0:
            return False, {}, 0.0

        rr = reward / risk

        if rr < 3.0:
            extra = candle_range * 3
            tp_alt = tp - extra
            reward_alt = entry - tp_alt
            if reward_alt > 0:
                rr_alt = reward_alt / risk
                if rr_alt >= 3.0:
                    return True, {
                        "entry": round(entry, 3),
                        "sl": round(sl, 3),
                        "tp": round(tp_alt, 3),
                    }, rr_alt
            return False, {}, rr
        else:
            return True, {
                "entry": round(entry, 3),
                "sl": round(sl, 3),
                "tp": round(tp, 3),
            }, rr

    else:
        return False, {}, 0.0


def _trend_mn(trend: str) -> str:
    if trend == "up":
        return "uptrend (өсөлт)"
    if trend == "down":
        return "downtrend (бууралт)"
    return "range / тодорхой бус"


# -------------------------------------------------------------------
# ГОЛ ПУБЛИК ФУНКЦ
# -------------------------------------------------------------------


def analyze_pair_multi_tf_ig_v2(ig, epic: str, pair: str) -> str:
    """
    IG client, epic, pair нэр (XAUUSD гэх мэт) авч:
    - D1, H4, H1, M15 candlestick татна
    - trend + түвшин тодорхойлно
    - Ганбаярын дүрмийн дагуу (D1+H4 чиглэл, R:R>=1:3, SL заавал г.м) setup хайна
    - Монгол тайлбар текст буцаана (Telegram бот шууд илгээхэд бэлэн)
    """

    lines = []
    lines.append("===== ГАНБАЯР MULTI-TF IG ANALYZER (v2) =====")
    lines.append(f"PAIR: {pair}")

    # ----------------- DATA TATAX -----------------
    try:
        d1_candles = ig.get_candles(epic, "DAY", max_points=200)
        h4_candles = ig.get_candles(epic, "HOUR_4", max_points=200)
        h1_candles = ig.get_candles(epic, "HOUR", max_points=200)
        m15_candles = ig.get_candles(epic, "MINUTE_15", max_points=200)
    except Exception as e:
        lines.append("")
        lines.append(f"❌ IG өгөгдөл татах үед алдаа гарлаа: {e}")
        return "\n".join(lines)

    # -------------- TREND + LEVELS ----------------
    d1_trend = _detect_trend(d1_candles)
    h4_trend = _detect_trend(h4_candles)
    h1_trend = _detect_trend(h1_candles)
    m15_trend = _detect_trend(m15_candles)

    d1_levels = _detect_levels(d1_candles)
    h4_levels = _detect_levels(h4_candles)
    m15_levels = _detect_levels(m15_candles)

    lines.append("D1:")
    lines.append(f"  Trend : { _trend_mn(d1_trend) }")
    lines.append(f"  Levels: {d1_levels}")
    lines.append("H4:")
    lines.append(f"  Trend : { _trend_mn(h4_trend) }")
    lines.append(f"  Levels: {h4_levels}")
    lines.append("H1:")
    lines.append(f"  Trend : { _trend_mn(h1_trend) }")
    lines.append("M15:")
    lines.append(f"  Trend : { _trend_mn(m15_trend) }")
    lines.append(f"  Levels: {m15_levels}")
    lines.append("")

    # -------------- D1 + H4 ЧИГЛЭЛ ----------------
    direction = _choose_direction(d1_trend, h4_trend)

    if direction == "none":
        lines.append(
            "ℹ NO TRADE: D1 ба H4 чиглэл хоорондоо давхцахгүй (эсвэл range) байгаа тул "
            "чанартай trend continuation setup хайхгүй."
        )
        return "\n".join(lines)

    dir_text = "BUY" if direction == "buy" else "SELL"
    lines.append(f"Ерөнхий чиглэл: {dir_text} (D1 + H4 зэрэгцсэн)")

    # -------------- M15 ДЭЭР ENTRY  ----------------
    has_setup, esltp, rr = _prepare_entry_sl_tp(direction, m15_candles, h4_levels)

    if not has_setup:
        lines.append("")
        lines.append(
            "ℹ NO TRADE: M15 дээрхи сүүлийн candle-аас авсан entry/SL-ийн хувьд "
            "H4 түвшин рүү чиглэсэн TP дээр R:R ≥ 1:3 гарахгүй байна. "
            "Ганбаярын дүрмээр энэ сетапыг алгаслаа."
        )
        lines.append(f"(Одоогийн R:R ойролцоогоор: {rr:.2f})")
        return "\n".join(lines)

    entry = esltp["entry"]
    sl = esltp["sl"]
    tp = esltp["tp"]

    lines.append("")
    lines.append(f"✅ Боломжит {dir_text} setup илэрлээ (R:R ≈ {rr:.2f})")
    lines.append(f"Entry: {entry}")
    lines.append(f"SL   : {sl}")
    lines.append(f"TP   : {tp}")
    lines.append("")
    lines.append("Тайлбар (Ганбаярын логик):")
    if direction == "buy":
        lines.append("- D1 ба H4 uptrend байгаа тул зөвхөн BUY setup хайсан.")
        lines.append("- H4 дээрх support түвшин дээрээс дээш хөдөлж буй гэж үзэж байна.")
    else:
        lines.append("- D1 ба H4 downtrend байгаа тул зөвхөн SELL setup хайсан.")
        lines.append("- H4 дээрх resistance түвшин дээрээс доош хөдөлж буй гэж үзэж байна.")
    lines.append(
        "- M15 дээр сүүлийн свечийн мэдээллээр entry, SL-ийг тооцоод, "
        "TP-ээ H4-ийн гол түвшин (support/resistance) рүү тавьж, R:R ≥ 1:3 эсэхийг шалгасан."
    )
    lines.append("- Stop Loss заавал байна, R:R < 1:3 бол сетапыг автоматаар алгасна.")
    lines.append("")
    lines.append("⚠ Санамж: Энэ бол зөвхөн анализ ба төлөвлөгөө. Шууд оролт хийхээсээ өмнө өөрөө дахин шалгана.")

    return "\n".join(lines)


# Хуучин нэршлийг дэмжих alias (ямар нэгэн хуучин код хэрэглэж байвал ажиллахын тулд)
def analyze_pair_multi_tf_ig(ig, epic: str, pair: str) -> str:
    return analyze_pair_multi_tf_ig_v2(ig, epic, pair)
