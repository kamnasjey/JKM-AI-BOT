"""
engine_blocks.py
----------------
User strategy engine-д ашиглагдах суурь "lego" блокүүд.

Энд зөвхөн цэвэр тооцоолол, дүн шинжилгээ хийнэ:
- IG candles-ийг normalize хийх
- Trend (MA) тодорхойлох
- Swing high/low + Fibonacci
- Support/Resistance, Pivot, Trendline, Channel
- Candlestick patterns
- Indicators (MA, Bollinger, MACD, Stochastic, RSI, PSAR)
- Market environment, ATR, breakout
- Multi-timeframe snapshot
- Correlation, divergence placeholder
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Any, Dict, List, Literal, Optional, Tuple


# ============================================================
# Суурь өгөгдлийн бүтэц
# ============================================================


@dataclass
class Candle:
    """Нэг лааны үндсэн мэдээлэл."""

    time: datetime
    open: float
    high: float
    low: float
    close: float


Direction = Literal["up", "down", "flat"]


# ============================================================
# IG candles -> Candle list хөрвүүлэх
# ============================================================


def normalize_candles(
    raw_candles: List[Dict[str, Any]],
    utc_offset_hours: int = 8,
) -> List[Candle]:
    """
    IG API-ээс ирсэн лаануудыг Candle жагсаалт болгоно.

    Цагийг UTC-аас utc_offset_hours-аар зөрүүлж хөрвүүлнэ.
    """
    candles: List[Candle] = []

    for c in raw_candles:
        t = c.get("time") or c.get("snapshotTimeUTC") or c.get("snapshotTime")

        if isinstance(t, str):
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

    candles.sort(key=lambda x: x.time)
    return candles


# ============================================================
# Moving average + trend
# ============================================================


def sma(values: List[float], period: int) -> List[float]:
    """Simple moving average-г бүх цэг дээр нь тооцож жагсаалт хэлбэрээр буцаана."""
    n = len(values)
    if n == 0 or period <= 0:
        return [0.0] * n
    if n < period:
        return [0.0] * n

    out: List[float] = []
    s = sum(values[:period])
    out.extend([0.0] * (period - 1))
    out.append(s / period)
    for i in range(period, n):
        s += values[i] - values[i - period]
        out.append(s / period)
    return out


def ema(values: List[float], period: int) -> List[float]:
    """Exponential moving average (классик 2/(period+1) жинтэй)."""
    n = len(values)
    if n == 0 or period <= 0:
        return [0.0] * n
    if n < period:
        return sma(values, period)

    out: List[float] = [0.0] * n
    k = 2.0 / (period + 1.0)

    # эхний EMA-г тухайн хэсгийн SMA-аар эхлүүлнэ
    first_ema = sum(values[:period]) / period
    for i in range(period - 1):
        out[i] = 0.0
    out[period - 1] = first_ema

    prev = first_ema
    for i in range(period, n):
        prev = values[i] * k + prev * (1.0 - k)
        out[i] = prev

    return out


@dataclass
class TrendInfo:
    """MA дээр суурилсан ерөнхий тренд мэдээлэл."""

    direction: Direction
    ma: float
    last_close: float


def detect_trend(
    candles: List[Candle],
    ma_period: int = 50,
    smooth_period: int = 10,
) -> TrendInfo:
    """
    Сүүлийн ma_period лааны SMA-г ашиглан тренд тогтооно.

    - last_close > MA, MA өсөж байвал -> up
    - last_close < MA, MA буурч байвал -> down
    - бусад тохиолдолд -> flat
    """
    if not candles:
        return TrendInfo(direction="flat", ma=0.0, last_close=0.0)

    closes = [c.close for c in candles]
    ma_series = sma(closes, ma_period)
    ma_now = ma_series[-1]
    if len(ma_series) > smooth_period:
        ma_prev = ma_series[-1 - smooth_period]
    else:
        ma_prev = ma_series[0]

    last_close = closes[-1]

    if last_close > ma_now and ma_now > ma_prev:
        direction: Direction = "up"
    elif last_close < ma_now and ma_now < ma_prev:
        direction = "down"
    else:
        direction = "flat"

    return TrendInfo(direction=direction, ma=ma_now, last_close=last_close)


# ============================================================
# Swing + Fibonacci
# ============================================================


@dataclass
class Swing:
    """Сүүлийн том хөдөлгөөний low/high бүс."""

    low: float
    high: float


@dataclass
class FiboZoneInfo:
    """Fibo retracement бүсэд үнэ орсон эсэх мэдээлэл."""

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
    Сүүлийн lookback лаан дотроос энгийн swing тодорхойлно.

    - up үед: хамгийн доод low -> хамгийн дээд high
    - down үед: хамгийн дээд high -> хамгийн доод low
    """
    if len(candles) < 10:
        return None

    segment = candles[-lookback:]

    # NOTE:
    # Previously this used raw min(low) and max(high) within lookback, which can
    # create a swing that never occurred in chronological order.
    # Here we enforce ordering:
    # - uptrend: lowest low, then highest high AFTER that low
    # - downtrend: highest high, then lowest low AFTER that high

    if direction == "up":
        low_idx = min(range(len(segment)), key=lambda i: segment[i].low)
        # Require a subsequent high (avoid degenerate swings)
        if low_idx >= len(segment) - 1:
            return None
        high_idx = max(range(low_idx + 1, len(segment)), key=lambda i: segment[i].high)
        swing_low = float(segment[low_idx].low)
        swing_high = float(segment[high_idx].high)
    elif direction == "down":
        high_idx = max(range(len(segment)), key=lambda i: segment[i].high)
        if high_idx >= len(segment) - 1:
            return None
        low_idx = min(range(high_idx + 1, len(segment)), key=lambda i: segment[i].low)
        swing_high = float(segment[high_idx].high)
        swing_low = float(segment[low_idx].low)
    else:
        return None

    if swing_high <= swing_low:
        return None

    return Swing(low=swing_low, high=swing_high)


def check_fibo_retrace_zone(
    candles: List[Candle],
    swing: Swing,
    levels: Tuple[float, float] = (0.5, 0.618),
    direction: Direction = "up",
) -> FiboZoneInfo:
    """
    Swing дээр тогтоосон 2 retrace түвшний хооронд
    сүүлийн хаалт байгаа эсэхийг шалгана.
    """
    last_close = candles[-1].close if candles else 0.0
    diff = swing.high - swing.low
    if diff <= 0:
        return FiboZoneInfo(False, 0.0, 0.0, last_close)

    if direction == "down":
        # Retrace for downtrend is measured from swing.high downward
        lvl1 = swing.high - diff * levels[0]
        lvl2 = swing.high - diff * levels[1]
    else:
        lvl1 = swing.low + diff * levels[0]
        lvl2 = swing.low + diff * levels[1]

    zone_low = min(lvl1, lvl2)
    zone_high = max(lvl1, lvl2)

    in_zone = zone_low <= last_close <= zone_high

    return FiboZoneInfo(
        in_zone=in_zone,
        zone_low=zone_low,
        zone_high=zone_high,
        last_close=last_close,
    )


@dataclass
class FiboLevels:
    """Fibonacci retracement ба extension түвшнүүд."""

    retrace: Dict[float, float]
    extensions: Dict[float, float]


def compute_fibo_levels(
    swing: Swing,
    retrace_levels: Tuple[float, ...] = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0),
    extension_levels: Tuple[float, ...] = (1.272, 1.618, 2.0, 2.618, 3.618),
    direction: Direction = "up",
) -> FiboLevels:
    """
    Swing дээр суурилсан бүх retracement, extension түвшинг тооцоолно.
    """
    diff = swing.high - swing.low
    if diff <= 0:
        return FiboLevels(retrace={}, extensions={})

    retrace: Dict[float, float] = {}
    if direction == "down":
        for lvl in retrace_levels:
            retrace[lvl] = swing.high - diff * lvl
    else:
        for lvl in retrace_levels:
            retrace[lvl] = swing.low + diff * lvl

    extensions: Dict[float, float] = {}
    if direction == "up":
        for lvl in extension_levels:
            extensions[lvl] = swing.low + diff * lvl
    else:
        for lvl in extension_levels:
            extensions[lvl] = swing.high - diff * lvl

    return FiboLevels(retrace=retrace, extensions=extensions)


def price_near_level(price: float, level_price: float, tolerance: float) -> bool:
    """Үнэ түвшнээс ±tolerance дотор ойрхон байна уу гэдгийг шалгана."""
    return abs(price - level_price) <= tolerance


# ============================================================
# Pip size + энгийн RR setup
# ============================================================


def estimate_pip_size(pair: str) -> float:
    """
    Хослолын pip хэмжээний энгийн таамаг.
    RR тооцоололд ашиглана.
    """
    pair_u = pair.upper()
    if pair_u.startswith("XAU"):
        return 0.1
    if "JPY" in pair_u:
        return 0.01
    return 0.0001


@dataclass
class Setup:
    """Энгийн BUY/SELL setup (RR дээр суурилсан)."""

    pair: str
    direction: Literal["BUY", "SELL"]
    entry: float
    sl: float
    tp: float
    rr: float
    trend_info: TrendInfo
    fibo_info: Optional[FiboZoneInfo]


def build_basic_setup_v2(
    *,
    pair: str,
    swing: Swing,
    trend: TrendInfo,
    fibo: Optional[FiboZoneInfo],
    min_rr: float,
    min_risk: float = 0.0,
) -> Optional[Setup]:
    """Price-difference дээр суурилсан setup builder.

    - Entry: trend.last_close
    - BUY үед SL: swing.low
    - SELL үед SL: swing.high
    - TP: risk * min_rr

    Pip тооцоолол ашиглахгүй.
    """
    if trend.direction == "up":
        direction: Literal["BUY", "SELL"] = "BUY"
    elif trend.direction == "down":
        direction = "SELL"
    else:
        return None

    if fibo is not None and not fibo.in_zone:
        return None

    entry = float(trend.last_close)
    if direction == "BUY":
        sl = float(swing.low)
        risk = entry - sl
        if risk <= 0:
            return None
        if risk < min_risk:
            sl = entry - min_risk
            risk = min_risk
        tp = entry + risk * float(min_rr)
    else:
        sl = float(swing.high)
        risk = sl - entry
        if risk <= 0:
            return None
        if risk < min_risk:
            sl = entry + min_risk
            risk = min_risk
        tp = entry - risk * float(min_rr)

    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0.0

    return Setup(
        pair=pair,
        direction=direction,
        entry=entry,
        sl=sl,
        tp=tp,
        rr=rr,
        trend_info=trend,
        fibo_info=fibo,
    )


def build_basic_setup(
    pair: str,
    trend: TrendInfo,
    fibo: Optional[FiboZoneInfo],
    risk_pips: float,
    min_rr: float,
) -> Optional[Setup]:
    """
    Trend + Fibo бүсийг ашиглан энгийн RR-тэй setup бүтээнэ.

    - trend.up -> BUY
    - trend.down -> SELL
    - flat үед trade үүсгэхгүй.
    """
    if trend.direction == "up":
        direction: Literal["BUY", "SELL"] = "BUY"
    elif trend.direction == "down":
        direction = "SELL"
    else:
        return None

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


# ============================================================
# Support & Resistance, Pivot
# ============================================================


@dataclass
class SRLevels:
    """Сүүлийн хэсгийн гол support ба resistance."""

    support: float
    resistance: float
    last_close: float


def find_sr_levels(candles: List[Candle], lookback: int = 50) -> SRLevels:
    """
    Сүүлийн lookback лаанаас хамгийн доод low, хамгийн дээд high-г
    support/resistance гэж үзнэ.
    """
    if not candles:
        return SRLevels(0.0, 0.0, 0.0)

    segment = candles[-lookback:]
    lows = [c.low for c in segment]
    highs = [c.high for c in segment]
    closes = [c.close for c in segment]

    support = min(lows)
    resistance = max(highs)
    last_close = closes[-1]

    return SRLevels(support=support, resistance=resistance, last_close=last_close)


@dataclass
class SRTouchInfo:
    """Үнэ support / resistance-д ойртсон эсэх мэдээлэл."""

    near_support: bool
    near_resistance: bool
    distance_to_support: float
    distance_to_resistance: float


def check_sr_touch(sr: SRLevels, tolerance_pips: float, pair: str) -> SRTouchInfo:
    """
    Үнэ support / resistance-д pip-ээр өгсөн хүлцэл дотор ойртох эсэхийг шалгана.
    """
    pip = estimate_pip_size(pair)
    tol_price = tolerance_pips * pip if pip > 0 else 0.0

    last = sr.last_close
    ds = abs(last - sr.support)
    dr = abs(last - sr.resistance)

    return SRTouchInfo(
        near_support=ds <= tol_price,
        near_resistance=dr <= tol_price,
        distance_to_support=ds / pip if pip > 0 else 0.0,
        distance_to_resistance=dr / pip if pip > 0 else 0.0,
    )


@dataclass
class PivotPoints:
    """Өмнөх өдрийн high/low/close-д суурилсан pivot point-ууд."""

    p: float
    r1: float
    r2: float
    s1: float
    s2: float


def compute_daily_pivots(prev_high: float, prev_low: float, prev_close: float) -> PivotPoints:
    """Classic floor trader pivot points тооцно."""
    p = (prev_high + prev_low + prev_close) / 3.0
    r1 = 2 * p - prev_low
    s1 = 2 * p - prev_high
    r2 = p + (prev_high - prev_low)
    s2 = p - (prev_high - prev_low)
    return PivotPoints(p=p, r1=r1, r2=r2, s1=s1, s2=s2)


# ============================================================
# Trendline & Channel
# ============================================================


@dataclass
class Trendline:
    """Хоёр цэг дээр суурилсан энгийн тренд шугам."""

    t1: datetime
    p1: float
    t2: datetime
    p2: float

    @property
    def slope(self) -> float:
        dt = (self.t2 - self.t1).total_seconds()
        if dt == 0:
            return 0.0
        return (self.p2 - self.p1) / dt

    def value_at(self, t: datetime) -> float:
        """Тухайн цаг дээрх тренд шугамын утгыг буцаана."""
        dt = (t - self.t1).total_seconds()
        return self.p1 + self.slope * dt


@dataclass
class Channel:
    """Дээд ба доод тренд шугамаас бүрдэх channel."""

    upper: Trendline
    lower: Trendline


def build_trendline_from_swings(
    candles: List[Candle],
    direction: Direction,
    lookback: int = 100,
) -> Optional[Trendline]:
    """
    Сүүлийн lookback лаанаас 2 гол low/high-оор тренд шугам үүсгэнэ.
    """
    if len(candles) < 10:
        return None

    segment = candles[-lookback:]

    if direction == "up":
        lows = sorted(segment, key=lambda c: c.low)[:2]
        if len(lows) < 2:
            return None
        lows.sort(key=lambda c: c.time)
        a, b = lows
        return Trendline(a.time, a.low, b.time, b.low)

    if direction == "down":
        highs = sorted(segment, key=lambda c: c.high, reverse=True)[:2]
        if len(highs) < 2:
            return None
        highs.sort(key=lambda c: c.time)
        a, b = highs
        return Trendline(a.time, a.high, b.time, b.high)

    return None


def build_simple_channel(
    candles: List[Candle],
    lookback: int = 120,
) -> Optional[Channel]:
    """
    Сүүлийн lookback лаанаас 2 low + 2 high ашиглан channel үүсгэнэ.
    """
    if len(candles) < 20:
        return None

    segment = candles[-lookback:]
    lows = sorted(segment, key=lambda c: c.low)[:2]
    highs = sorted(segment, key=lambda c: c.high, reverse=True)[:2]

    if len(lows) < 2 or len(highs) < 2:
        return None

    lows.sort(key=lambda c: c.time)
    highs.sort(key=lambda c: c.time)

    lower = Trendline(lows[0].time, lows[0].low, lows[1].time, lows[1].low)
    upper = Trendline(highs[0].time, highs[0].high, highs[1].time, highs[1].high)

    return Channel(upper=upper, lower=lower)


def is_price_near_trendline(
    candles: List[Candle],
    trendline: Trendline,
    tolerance_pips: float,
    pair: str,
) -> bool:
    """Сүүлийн лааны хаалт тренд шугамд ойрхон эсэхийг шалгана."""
    if not candles:
        return False
    pip = estimate_pip_size(pair)
    if pip <= 0:
        return False
    last = candles[-1]
    lvl = trendline.value_at(last.time)
    tol = tolerance_pips * pip
    return abs(last.close - lvl) <= tol


# ============================================================
# Candlestick patterns
# ============================================================

CandlestickPattern = Literal[
    "doji",
    "spinning_top",
    "marubozu",
    "hammer",
    "hanging_man",
    "inverted_hammer",
    "shooting_star",
    "bullish_engulfing",
    "bearish_engulfing",
    "tweezer_top",
    "tweezer_bottom",
    "morning_star",
    "evening_star",
    "three_white_soldiers",
    "three_black_crows",
    "three_inside_up",
    "three_inside_down",
]


@dataclass
class CandlePatternSignal:
    """Илэрсэн candlestick pattern-ийн дохио."""

    pattern: CandlestickPattern
    direction: Literal["bullish", "bearish", "neutral"]
    at_time: datetime


def _body_and_shadows(c: Candle) -> Tuple[float, float, float]:
    """Body, upper, lower shadow хэмжээг тооцно."""
    body = abs(c.close - c.open)
    upper = c.high - max(c.open, c.close)
    lower = min(c.open, c.close) - c.low
    return body, upper, lower


def detect_single_candle_patterns(last: Candle) -> List[CandlePatternSignal]:
    """
    Нэг лаан дээр суурилсан pattern-уудыг илрүүлнэ.
    """
    body, upper, lower = _body_and_shadows(last)
    total = last.high - last.low or 1e-6
    res: List[CandlePatternSignal] = []

    # Doji
    if body <= total * 0.1:
        res.append(CandlePatternSignal("doji", "neutral", last.time))

    # Spinning top
    if body <= total * 0.3 and upper > body and lower > body:
        res.append(CandlePatternSignal("spinning_top", "neutral", last.time))

    # Marubozu
    if body >= total * 0.8:
        direction = "bullish" if last.close > last.open else "bearish"
        res.append(CandlePatternSignal("marubozu", direction, last.time))

    # Hammer / Hanging man
    if lower >= body * 2.5 and upper <= body * 0.5:
        if last.close >= last.open:
            res.append(CandlePatternSignal("hammer", "bullish", last.time))
        else:
            res.append(CandlePatternSignal("hanging_man", "bearish", last.time))

    # Inverted hammer / Shooting star
    if upper >= body * 2.5 and lower <= body * 0.5:
        if last.close >= last.open:
            res.append(CandlePatternSignal("inverted_hammer", "bullish", last.time))
        else:
            res.append(CandlePatternSignal("shooting_star", "bearish", last.time))

    return res


def detect_multi_candle_patterns(candles: List[Candle]) -> List[CandlePatternSignal]:
    """
    Олон лаанаас бүрдэх pattern-уудыг (engulfing, tweezer, star, three soldiers/crows, three inside) илрүүлнэ.
    """
    res: List[CandlePatternSignal] = []
    n = len(candles)
    if n < 2:
        return res

    c1 = candles[-2]
    c2 = candles[-1]

    # Engulfing
    if c1.close < c1.open and c2.close > c2.open:
        if c2.open < c1.close and c2.close > c1.open:
            res.append(CandlePatternSignal("bullish_engulfing", "bullish", c2.time))
    if c1.close > c1.open and c2.close < c2.open:
        if c2.open > c1.close and c2.close < c1.open:
            res.append(CandlePatternSignal("bearish_engulfing", "bearish", c2.time))

    # Tweezer top/bottom
    if abs(c1.high - c2.high) <= (c1.high - c1.low) * 0.1:
        res.append(CandlePatternSignal("tweezer_top", "bearish", c2.time))
    if abs(c1.low - c2.low) <= (c1.high - c1.low) * 0.1:
        res.append(CandlePatternSignal("tweezer_bottom", "bullish", c2.time))

    if n >= 3:
        a, b, c = candles[-3], candles[-2], candles[-1]

        # Morning star
        if (
            a.close < a.open
            and abs(b.close - b.open) < abs(a.close - a.open) * 0.6
            and c.close > c.open
            and c.close > (a.open + a.close) / 2
        ):
            res.append(CandlePatternSignal("morning_star", "bullish", c.time))

        # Evening star
        if (
            a.close > a.open
            and abs(b.close - b.open) < abs(a.close - a.open) * 0.6
            and c.close < c.open
            and c.close < (a.open + a.close) / 2
        ):
            res.append(CandlePatternSignal("evening_star", "bearish", c.time))

        # Three white soldiers
        last3 = candles[-3:]
        if all(x.close > x.open for x in last3):
            if last3[0].close < last3[1].close < last3[2].close:
                res.append(
                    CandlePatternSignal(
                        "three_white_soldiers", "bullish", last3[-1].time
                    )
                )

        # Three black crows
        if all(x.close < x.open for x in last3):
            if last3[0].close > last3[1].close > last3[2].close:
                res.append(
                    CandlePatternSignal(
                        "three_black_crows", "bearish", last3[-1].time
                    )
                )

        # Three inside up/down (simple harami + confirmation)
        inner_small = abs(b.close - b.open) < abs(a.close - a.open)
        if inner_small:
            # Three inside up
            if (
                a.close < a.open
                and b.open > a.close
                and b.close < a.open
                and c.close > a.open
            ):
                res.append(CandlePatternSignal("three_inside_up", "bullish", c.time))
            # Three inside down
            if (
                a.close > a.open
                and b.open < a.close
                and b.close > a.open
                and c.close < a.open
            ):
                res.append(CandlePatternSignal("three_inside_down", "bearish", c.time))

    return res


# ============================================================
# Индикаторууд (Bollinger, MACD, Stochastic, RSI, PSAR)
# ============================================================


@dataclass
class BollingerBands:
    """Bollinger band-ийн сүүлийн утгууд."""

    middle: float
    upper: float
    lower: float


def compute_bollinger_bands(
    candles: List[Candle],
    period: int = 20,
    std_mul: float = 2.0,
) -> Optional[BollingerBands]:
    """Сүүлийн period лаан дээр Bollinger band тооцно."""
    if len(candles) < period:
        return None
    closes = [c.close for c in candles]
    window = closes[-period:]
    m = mean(window)
    sd = pstdev(window) if period > 1 else 0.0
    return BollingerBands(middle=m, upper=m + sd * std_mul, lower=m - sd * std_mul)


@dataclass
class MACDResult:
    """MACD-ийн сүүлийн утгууд."""

    macd: float
    signal: float
    hist: float


def compute_macd(
    candles: List[Candle],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Optional[MACDResult]:
    """MACD (EMA суурь) индикаторыг тооцно."""
    closes = [c.close for c in candles]
    if len(closes) < slow_period + signal_period:
        return None

    ema_fast = ema(closes, fast_period)
    ema_slow = ema(closes, slow_period)
    macd_series = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_series = ema(macd_series, signal_period)

    macd_val = macd_series[-1]
    signal_val = signal_series[-1]
    hist_val = macd_val - signal_val

    return MACDResult(macd=macd_val, signal=signal_val, hist=hist_val)


@dataclass
class StochasticResult:
    """Stochastic oscillator-ийн сүүлийн утгууд."""

    k: float
    d: float


def compute_stochastic(
    candles: List[Candle],
    k_period: int = 14,
    d_period: int = 3,
) -> Optional[StochasticResult]:
    """%K, %D утгыг тооцно."""
    if len(candles) < k_period + d_period:
        return None

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    closes = [c.close for c in candles]

    k_values: List[float] = []
    for i in range(k_period - 1, len(candles)):
        hh = max(highs[i - k_period + 1 : i + 1])
        ll = min(lows[i - k_period + 1 : i + 1])
        c = closes[i]
        if hh == ll:
            k_values.append(50.0)
        else:
            k_values.append((c - ll) / (hh - ll) * 100.0)

    if len(k_values) < d_period:
        return None

    k = k_values[-1]
    d = mean(k_values[-d_period:])

    return StochasticResult(k=k, d=d)


@dataclass
class RSIResult:
    """RSI индикаторын сүүлийн утга."""

    value: float


def compute_rsi(candles: List[Candle], period: int = 14) -> Optional[RSIResult]:
    """Wilder-ийн классик томъёогоор RSI тооцно."""
    if len(candles) < period + 1:
        return None

    closes = [c.close for c in candles]
    gains: List[float] = []
    losses: List[float] = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)

    avg_gain = mean(gains[:period])
    avg_loss = mean(losses[:period])
    if avg_loss == 0:
        return RSIResult(100.0)

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

    return RSIResult(value=rsi)


@dataclass
class PSARResult:
    """Parabolic SAR-ийн сүүлийн утга ба чиглэл."""

    value: float
    direction: Direction


def compute_parabolic_sar(
    candles: List[Candle],
    af_step: float = 0.02,
    af_max: float = 0.2,
) -> Optional[PSARResult]:
    """
    Энгийн Parabolic SAR алгоритм.

    Энэ нь зөвхөн сүүлийн SAR утга болон чиглэлийг буцаана.
    """
    n = len(candles)
    if n < 5:
        return None

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    direction: Direction = "up" if highs[1] - lows[0] >= 0 else "down"
    af = af_step
    ep = highs[0] if direction == "up" else lows[0]
    psar = lows[0] if direction == "up" else highs[0]

    for i in range(1, n):
        prev_psar = psar
        if direction == "up":
            psar = prev_psar + af * (ep - prev_psar)
            psar = min(psar, lows[i - 1], lows[i])
            if highs[i] > ep:
                ep = highs[i]
                af = min(af + af_step, af_max)
            if lows[i] < psar:
                direction = "down"
                psar = ep
                ep = lows[i]
                af = af_step
        else:
            psar = prev_psar + af * (ep - prev_psar)
            psar = max(psar, highs[i - 1], highs[i])
            if lows[i] < ep:
                ep = lows[i]
                af = min(af + af_step, af_max)
            if highs[i] > psar:
                direction = "up"
                psar = ep
                ep = highs[i]
                af = af_step

    return PSARResult(value=psar, direction=direction)


# ============================================================
# Market environment + ATR + breakout
# ============================================================


@dataclass
class MarketEnvironment:
    """Зах зээлийн ерөнхий орчны товч ангилал."""

    trend: Direction
    volatility: float  # ATR
    is_range: bool
    is_breakout: bool


def compute_atr(candles: List[Candle], period: int = 14) -> float:
    """ATR (Average True Range)-ийн ойролцоо утгыг буцаана."""
    if len(candles) < period + 1:
        return 0.0

    trs: List[float] = []
    for i in range(1, len(candles)):
        h = candles[i].high
        l = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        trs.append(tr)

    if len(trs) < period:
        return mean(trs)
    return mean(trs[-period:])


def classify_market_environment(
    candles: List[Candle],
    sr: Optional[SRLevels] = None,
    ma_period: int = 50,
) -> MarketEnvironment:
    """
    Trend + ATR + SR ашиглаад зах зээлийн орчныг ангилна
    (trend, range, breakout).
    """
    trend_info = detect_trend(candles, ma_period=ma_period)
    atr = compute_atr(candles)
    last = candles[-1] if candles else Candle(datetime.utcnow(), 0, 0, 0, 0)

    is_range = False
    is_breakout = False

    if sr is not None:
        mid = (sr.support + sr.resistance) / 2.0
        width = sr.resistance - sr.support
        if width > 0:
            is_range = abs(last.close - mid) < width * 0.25

        if last.close > sr.resistance or last.close < sr.support:
            is_breakout = True

    return MarketEnvironment(
        trend=trend_info.direction,
        volatility=atr,
        is_range=is_range,
        is_breakout=is_breakout,
    )


# ============================================================
# Divergence placeholder
# ============================================================


@dataclass
class DivergenceSignal:
    """RSI divergence дохионы placeholder."""

    kind: Literal["bullish", "bearish"]
    at_time: datetime


def detect_rsi_divergence(
    candles: List[Candle],
    rsi: RSIResult,
    rsi_series_period: int = 14,
) -> Optional[DivergenceSignal]:
    """
    RSI divergence шалгах суурь функц.

    Одоогоор бүрэн гүйцэд хэрэгжүүлээгүй.
    Аюулгүй байлгахын тулд одоохондоо үргэлж None буцаана.
    """
    _ = (candles, rsi, rsi_series_period)
    return None


# ============================================================
# Correlation (үнэт цаасны хамаарал)
# ============================================================


def compute_correlation(closes_a: List[float], closes_b: List[float]) -> float:
    """
    Хоёр цувралын хоорондын Pearson correlation (-1..+1) тооцно.
    """
    n = min(len(closes_a), len(closes_b))
    if n < 5:
        return 0.0

    a = closes_a[-n:]
    b = closes_b[-n:]
    ma = mean(a)
    mb = mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den_a = sum((x - ma) ** 2 for x in a)
    den_b = sum((y - mb) ** 2 for y in b)
    if den_a == 0 or den_b == 0:
        return 0.0
    return num / ((den_a ** 0.5) * (den_b ** 0.5))


# ============================================================
# Multi-timeframe snapshot (D1, H4, H1, M15 ...)
# ============================================================


@dataclass
class TimeframeSnapshot:
    """Нэг timeframe-ийн товч дүгнэлт."""

    tf: str
    trend: TrendInfo
    sr: SRLevels
    env: MarketEnvironment


@dataclass
class MultiTFSnapshot:
    """Олон timeframe-ийн нийлмэл зураг."""

    pair: str
    tfs: List[TimeframeSnapshot]


def build_multi_tf_snapshot(
    pair: str,
    tf_to_candles: Dict[str, List[Candle]],
    ma_period: int = 50,
) -> MultiTFSnapshot:
    """
    Өгөгдсөн TF бүрийн лаа дээр үндэслэж олон TF-н snapshot үүсгэнэ.
    Telegram/AI текстэн дүгнэлтэд ашиглахад тохиромжтой.
    """
    snapshots: List[TimeframeSnapshot] = []
    for tf, candles in tf_to_candles.items():
        if not candles:
            continue
        trend = detect_trend(candles, ma_period=ma_period)
        sr = find_sr_levels(candles)
        env = classify_market_environment(candles, sr=sr, ma_period=ma_period)
        snapshots.append(TimeframeSnapshot(tf=tf, trend=trend, sr=sr, env=env))

    return MultiTFSnapshot(pair=pair, tfs=snapshots)
