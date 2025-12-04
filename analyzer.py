from rr_filter import check_rr

# Candle-ийг энгийн dict байдлаар ашиглая: {"close": 2600, "high": ..., "low": ...}


def detect_trend(candles: list[dict]) -> str:
    """
    Сүүлийн хэдэн close-оор чиглэл тодорхойлно.
    Маш энгийн: өсөөд байвал up, унаад байвал down, бусад нь range.
    """
    closes = [c["close"] for c in candles[-5:]]

    if len(closes) < 3:
        return "range"

    if closes[-1] > closes[-2] > closes[-3]:
        return "up"
    if closes[-1] < closes[-2] < closes[-3]:
        return "down"

    return "range"


def find_key_levels(candles: list[dict]) -> dict:
    """
    Маш энгийн support / resistance: бүх closes-ийн min/max.
    Жинхэнэ ботод илүү нарийн алгоритм орно.
    """
    closes = [c["close"] for c in candles]
    support = min(closes)
    resistance = max(closes)
    return {"support": support, "resistance": resistance}


def build_fake_candles(start: float, step: float, n: int) -> list[dict]:
    """
    Жаахан хиймэл trend үүсгэж өгнө (жишээ dataset).
    start: эхний үнэ
    step: алхам (эерэг бол өснө, сөрөг бол унана)
    """
    candles = []
    price = start
    for _ in range(n):
        close = price
        high = close + abs(step) * 0.6
        low = close - abs(step) * 0.6
        candles.append({"close": close, "high": high, "low": low})
        price += step
    return candles


def analyze_pair_fake(pair: str) -> dict | None:
    """
    D1, H4, H1, M30, M15 бүх timeframe-д хиймэл data үүсгээд,
    Ганбаярын философоор нэг BUY setup гаргаж үзнэ.
    """

    # --- 1. D1 + H4: чиглэл, түвшин ---
    d1 = build_fake_candles(start=2350, step=5, n=50)   # өсч байгаа daily
    h4 = build_fake_candles(start=2420, step=3, n=60)   # өсөлттэй

    d1_trend = detect_trend(d1)
    h4_trend = detect_trend(h4)
    d1_levels = find_key_levels(d1)
    h4_levels = find_key_levels(h4)

    # Ганбаярын логик: D1 + H4 хоёул up байвал BUY тал хайна
    if not (d1_trend == "up" and h4_trend == "up"):
        return None  # одоохондоо зөвхөн uptrend case

    # --- 2. H1 + M30: pullback / zone ---
    h1 = build_fake_candles(start=2440, step=-1.5, n=80)   # жаахан pullback
    m30 = build_fake_candles(start=2435, step=-0.8, n=60)

    h1_levels = find_key_levels(h1)
    m30_levels = find_key_levels(m30)

    # support бүсийг ойролцоогоор тогтооно (жишээ)
    buy_zone_low = h1_levels["support"]
    buy_zone_high = buy_zone_low + 5
    buy_zone = (buy_zone_low, buy_zone_high)

    # ---
