# engine_blocks.py
"""
engine_blocks.py
----------------
User strategy engine-д ашиглагдах суурь "lego" блокүүд.
- IG candles-ийг normalize хийх
- Trend (MA суурь) тодорхойлох
- Swing high/low олох
- Fibo retracement бүс тооцоолох
- PIP хэмжээ таамаглах
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Dict, List, Literal, Optional, Tuple


# ------------------------------------------------------------
# Өгөгдлийн basic бүтэц
# ------------------------------------------------------------

@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float


Direction = Literal["up", "down", "flat"]


# ------------------------------------------------------------
# IG candles -> Candle list хөрвүүлэх
# ------------------------------------------------------------

def normalize_candles(
    raw_candles: List[Dict[str, Any]],
    utc_offset_hours: int = 8,
) -> List[Candle]:
    """
    IGClient.get_candles()–ээс ирсэн үйлчилгээний dict-үүдийг
    дотооддоо ашиглах Candle dataclass руу хөрвүүлнэ.
    snapshotTimeUTC эсвэл time талбар дээр суурилж UTC+offset руу хувиргана.
    """
    candles: List[Candle] = []

    for c in raw_candles:
        t = c.get("time") or c.get("snapshotTimeUTC") or c.get("snapshotTime")

        if isinstance(t, str):
            # "2024-01-01T12:00:00" эсвэл "2024-01-01T12:00:00+00:00"
            if t.endswith("Z"):
                t = t.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(t)
            except Exception:
                dt = datetime.utcnow()
        elif isinstance(t, datetime):
            dt = t
        else:
            dt = datetime.utcnow()

        dt_local = dt + timedelta(hours=utc_offset_hours)

        candles.append(
            Candle(
                time=dt_local,
                open=float(c["open"]),
                high=float(c["high"]),
                low=float(c["low"]),
                close=float(c["close"]),
            )
        )

    # Цагаар нь эрэмбэлчихье
    candles.sort(key=lambda x: x.time)
    return candles


# ------------------------------------------------------------
# Trend (MA) блок
# ------------------------------------------------------------

@dataclass
class TrendInfo:
    direction: Direction
    ma: float
    last_close: float


def detect_trend(
    candles: List[Candle],
    ma_period: int = 50,
    smooth_period: int = 10,
) -> TrendInfo:
    """
    Сүүлийн ma_period лааны хаалтын дундажийг авч,
    чиглэлийг энгийнээр тодорхойлно.
    """
    if len(candles) < ma_period + smooth_period:
        # Мэдээлэл бага байвал flat гэж үзье
        last_close = candles[-1].close if candles else 0.0
        return TrendInfo(direction="flat", ma=last_close, last_close=last_close)

    closes = [c.close for c in candles]

    ma_now = mean(closes[-ma_period:])
    ma_prev = mean(closes[-ma_period - smooth_period : -smooth_period])
    last_close = closes[-1]

    if last_close > ma_now and ma_now > ma_prev:
        direction: Direction = "up"
    elif last_close < ma_now and ma_now < ma_prev:
        direction = "down"
    else:
        direction = "flat"

    return TrendInfo(direction=direction, ma=ma_now, last_close=last_close)


# ------------------------------------------------------------
# Swing + Fibo блок
# ------------------------------------------------------------

@dataclass
class Swing:
    low: float
    high: float


@dataclass
class FiboZoneInfo:
    in_zone: bool
    zone_low: float
    zone_high: float
    last_close: float


def find_last_swing(
    candles: List[Candle],
    lookback: int = 80,
    direction: Direction = "up",
) -> Optional[Swing]:
    """
    Сүүлийн lookback лаан дотроос:
      - up бол хамгийн доод low -> хамгийн дээд high
      - down бол хамгийн дээд high -> хамгийн доод low
    гэж энгийн swing тодорхойлоод буцаана.
    """
    if len(candles) < 10:
        return None

    segment = candles[-lookback:]
    highs = [c.high for c in segment]
    lows = [c.low for c in segment]

    if not highs or not lows:
        return None

    if direction == "up":
        swing_low = min(lows)
        swing_high = max(highs)
    elif direction == "down":
        swing_high = max(highs)
        swing_low = min(lows)
    else:
        # flat үед swing тодорхойлох шаардлагагүй
        return None

    if swing_high <= swing_low:
        return None

    return Swing(low=swing_low, high=swing_high)


def check_fibo_retrace_zone(
    candles: List[Candle],
    swing: Swing,
    levels: Tuple[float, float] = (0.5, 0.618),
) -> FiboZoneInfo:
    """
    Swing дээр fibo retracement 2 түвшин тооцоолж,
    хамгийн сүүлийн хаалтын үнэ тэр бүсэд орсон эсэхийг шалгана.
    """
    last_close = candles[-1].close if candles else 0.0

    low = swing.low
    high = swing.high
    diff = high - low
    if diff <= 0:
        return FiboZoneInfo(False, 0, 0, last_close)

    lvl1 = low + diff * levels[0]
    lvl2 = low + diff * levels[1]

    zone_low = min(lvl1, lvl2)
    zone_high = max(lvl1, lvl2)

    in_zone = zone_low <= last_close <= zone_high

    return FiboZoneInfo(
        in_zone=in_zone,
        zone_low=zone_low,
        zone_high=zone_high,
        last_close=last_close,
    )


# ------------------------------------------------------------
# PIP хэмжээ + SL/TP тооцоо
# ------------------------------------------------------------

def estimate_pip_size(pair: str) -> float:
    pair_u = pair.upper()
    if pair_u.startswith("XAU"):
        # XAUUSD дээр 0.1-ыг 1 pip гэж үзье
        return 0.1
    if "JPY" in pair_u:
        return 0.01
    return 0.0001


@dataclass
class Setup:
    pair: str
    direction: Literal["BUY", "SELL"]
    entry: float
    sl: float
    tp: float
    rr: float
    trend_info: TrendInfo
    fibo_info: Optional[FiboZoneInfo]


def build_basic_setup(
    pair: str,
    trend: TrendInfo,
    fibo: Optional[FiboZoneInfo],
    risk_pips: float,
    min_rr: float,
) -> Optional[Setup]:
    """
    Trend + Fibo zone (байж байвал)–ийг ашиглаад энгийн BUY/SELL setup гаргана.
    - Trend UP -> BUY
    - Trend DOWN -> SELL
    - FLAT -> trade алгасна
    """
    direction: Literal["BUY", "SELL"]

    if trend.direction == "up":
        direction = "BUY"
    elif trend.direction == "down":
        direction = "SELL"
    else:
        return None

    # Хэрвээ fibo өгөгдсөн бол zone-д байгаа эсэхийг шалгана
    if fibo is not None and not fibo.in_zone:
        return None

    entry = trend.last_close
    pip = estimate_pip_size(pair)
    if pip <= 0:
        return None

    if direction == "BUY":
        sl = entry - pip * risk_pips
        tp = entry + pip * risk_pips * min_rr
    else:
        sl = entry + pip * risk_pips
        tp = entry - pip * risk_pips * min_rr

    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk <= 0:
        return None

    rr = reward / risk

    return Setup(
        pair=pair,
        direction=direction,
        entry=round(entry, 5),
        sl=round(sl, 5),
        tp=round(tp, 5),
        rr=rr,
        trend_info=trend,
        fibo_info=fibo,
    )
