# strategy.py
"""
ГАНБАЯР v2 – Multi TF + Fib + R:R ≥ 1:3 суурь стратеги.

Одоогоор:
  - D1 + H4 дээр чиглэл, том түвшин, Fib retracement сайнцагаан
  - H1 + M15 дээр entry бүс + entry point
  - Fib extension дээр TP, R:R ≥ 1:3 шалгана
  - BUY / SELL аль алинд нь ажиллана

Цаашид:
  - M30, M5 structure break
  - Candle pattern (engulfing, pin)
  - News filter, risk % гэх мэтийг эндээс үргэлжлүүлнэ.
"""

from typing import Any, Dict, List, Literal, Optional

from analyzer import detect_trend, find_key_levels

Direction = Literal["BUY", "SELL"]


# ---------------- Туслах функцууд ----------------

def _get_last_swing(candles: List[Dict[str, float]]) -> Dict[str, float]:
    """
    H4/D1 дээр хамгийн сүүлийн импульсийг барагцаалж авах helper.
    Одоогоор сүүлийн 20–30 свеч доторх хамгийн өндөр / хамгийн намыг авна.
    """
    if len(candles) < 5:
        return {}

    window = candles[-30:]
    high = max(window, key=lambda c: c["high"])
    low = min(window, key=lambda c: c["low"])

    return {"swing_high": high["high"], "swing_low": low["low"]}


def _fib_retracement_levels(swing_high: float, swing_low: float) -> Dict[str, float]:
    """
    Fib retracement түвшинүүд (0.382 / 0.5 / 0.618 / 0.786).
    Uptrend үед low→high, downtrend үед high→low гэж ойлгож болно.
    """
    diff = swing_high - swing_low
    return {
        "0.382": swing_high - diff * 0.382,
        "0.5": swing_high - diff * 0.5,
        "0.618": swing_high - diff * 0.618,
        "0.786": swing_high - diff * 0.786,
    }


def _fib_extension_levels(a: float, b: float, c: float, direction: Direction) -> Dict[str, float]:
    """
    Fib extension 1.272, 1.618 түвшинүүд.
    Uptrend BUY:
      A = swing low, B = swing high, C = pullback low
    Downtrend SELL:
      A = swing high, B = swing low, C = pullback high
    """
    if direction == "BUY":
        diff = b - a
        return {
            "1.272": c + diff * 1.272,
            "1.618": c + diff * 1.618,
        }
    else:
        diff = a - b
        return {
            "1.272": c - diff * 1.272,
            "1.618": c - diff * 1.618,
        }


def _pick_tp_with_rr_generic(
    entry: float,
    sl: float,
    tp_candidates: List[float],
    direction: Direction,
    min_rr: float = 3.0,
) -> Optional[Dict[str, float]]:
    """
    Entry, SL, TP кандидатууд дээрээс R:R ≥ min_rr хангах эхний TP-ийг сонгоно.
    BUY/SELL аль алинд ашиглана.
    """
    risk = abs(entry - sl)
    if risk <= 0:
        return None

    for tp in tp_candidates:
        if direction == "BUY":
            reward = tp - entry
        else:
            reward = entry - tp

        if reward <= 0:
            continue

        rr = reward / risk
        if rr >= min_rr:
            return {"tp": tp, "rr": rr}

    return None


# ---------------- Үндсэн стратеги ----------------

def analyze_xauusd_full(
    d1_candles: List[Dict[str, Any]],
    h4_candles: List[Dict[str, Any]],
    h1_candles: List[Dict[str, Any]],
    m15_candles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Бүрэн multi-timeframe анализ:

      - D1: Trend + том S/R
      - H4: Structure + сүүлийн импульс + Fib retracement (0.5–0.618)
      - H1: Үнэ Fib бүс дотор ирсэн эсэх
      - M15: Entry candle (одоогоор сүүлийн свеч)
      - Fib extension 1.272 / 1.618 дээр TP сонгож, R:R ≥ 1:3 шалгана.
    """

    if not d1_candles or not h4_candles or not h1_candles or not m15_candles:
        return {
            "status": "no_data",
            "reason": "Ядаж нэг timeframe-ийн свеч байхгүй байна.",
        }

    # 1) D1 – чиглэл, том S/R
    d1_trend = detect_trend(d1_candles)
    d1_levels = find_key_levels(d1_candles)

    # 2) H4 – structure + импульс + Fib retracement
    h4_trend = detect_trend(h4_candles)
    h4_levels = find_key_levels(h4_candles)
    h4_swing = _get_last_swing(h4_candles)

    base: Dict[str, Any] = {
        "pair": "XAUUSD",
        "d1_trend": d1_trend,
        "d1_levels": d1_levels,
        "h4_trend": h4_trend,
        "h4_levels": h4_levels,
        "entry_tf": "M15",
    }

    if not h4_swing:
        return {
            **base,
            "status": "no_data",
            "reason": "H4 swing тодорхойлох боломжгүй байна.",
        }

    swing_high = h4_swing["swing_high"]
    swing_low = h4_swing["swing_low"]

    # D1 + H4 нийлж ерөнхий чиглэл
    if d1_trend == h4_trend:
        main_trend = d1_trend
    else:
        main_trend = h4_trend  # одоохондоо H4-д илүү жин өгнө

    if main_trend not in ("up", "down"):
        return {
            **base,
            "status": "no_trade",
            "reason": "D1/H4 дээр тодорхой up/down биш (range эсвэл unclear).",
        }

    # 3) H4 Fib retracement zone (0.5–0.618)
    if main_trend == "up":
        fib_retr = _fib_retracement_levels(swing_high, swing_low)
        fib_zone = (fib_retr["0.5"], fib_retr["0.618"])
        direction: Direction = "BUY"
    else:
        # downtrend – high→low татсан гэж үзээд zone-г урвуу авна
        fib_retr = _fib_retracement_levels(swing_low, swing_high)
        fib_zone = (fib_retr["0.5"], fib_retr["0.618"])
        direction = "SELL"

    z_min, z_max = sorted(fib_zone)

    # 4) H1 – үнэ Fib zone-д орсон эсэх
    last_h1 = h1_candles[-1]
    h1_price = last_h1["close"]

    price_in_zone = z_min <= h1_price <= z_max

    if not price_in_zone:
        return {
            **base,
            "status": "no_trade",
            "reason": "H1 үнэ Fib 0.5–0.618 бүсэд хараахан ороогүй байна.",
            "fib_zone": fib_zone,
            "h1_price": h1_price,
        }

    # 5) M15 – entry (одоогоор хамгийн сүүлийн свеч дээр үндэслэнэ)
    last_m15 = m15_candles[-1]
    entry = last_m15["close"]

    if direction == "BUY":
        sl = last_m15["low"] - 2.0
        a = swing_low
        b = swing_high
        c = last_m15["low"]
    else:
        sl = last_m15["high"] + 2.0
        a = swing_high
        b = swing_low
        c = last_m15["high"]

    # 6) Fib extension 1.272 / 1.618 дээр TP кандидатууд
    fib_ext = _fib_extension_levels(a, b, c, direction)
    tp_candidates = [fib_ext["1.272"], fib_ext["1.618"]]

    # 7) R:R ≥ 1:3 шалгах
    rr_pick = _pick_tp_with_rr_generic(entry, sl, tp_candidates, direction, min_rr=3.0)

    if not rr_pick:
        return {
            **base,
            "status": "no_trade_rr",
            "reason": "Fib extension дээр R:R ≥ 1:3 хангах TP олдсонгүй.",
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp_candidates": tp_candidates,
            "fib_zone": fib_zone,
        }

    tp = rr_pick["tp"]
    rr = rr_pick["rr"]

    return {
        **base,
        "status": "trade",
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr": rr,
        "fib_zone": fib_zone,
        "tp_candidates": tp_candidates,
    }
