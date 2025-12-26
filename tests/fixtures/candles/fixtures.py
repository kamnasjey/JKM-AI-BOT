from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from engine_blocks import Candle


def _mk_candle(*, t: datetime, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(time=t, open=float(o), high=float(h), low=float(l), close=float(c))


def _series_from_closes(
    closes: List[float],
    *,
    start: datetime = datetime(2020, 1, 1, 0, 0, 0),
    step_min: int = 15,
    wick: float = 0.08,
) -> List[Candle]:
    out: List[Candle] = []
    t = start
    prev_close = float(closes[0])
    for i, close in enumerate(closes):
        c = float(close)
        o = float(prev_close if i > 0 else c)
        # Add a tiny deterministic epsilon so adjacent candles at turning points
        # don't end up with identical highs/lows (which would suppress strict
        # fractal swing detection).
        eps = 1e-6 * float(i)
        hi = max(o, c) + float(wick) + eps
        lo = min(o, c) - float(wick) - eps
        out.append(_mk_candle(t=t, o=o, h=hi, l=lo, c=c))
        prev_close = c
        t = t + timedelta(minutes=int(step_min))
    return out


def _range_base(*, n: int = 80, mid: float = 101.0, amp: float = 1.0) -> List[Candle]:
    closes: List[float] = []
    # Deterministic oscillation (no random).
    for i in range(int(n)):
        phase = i % 10
        # Triangle wave in [-1, 1]
        tri = (phase / 5.0) - 1.0 if phase <= 5 else 1.0 - ((phase - 5) / 5.0)
        closes.append(float(mid + amp * tri))
    return _series_from_closes(closes, wick=0.12)


def _uptrend_zigzag(*, n: int = 90, start: float = 100.0, step: float = 0.12, swing: float = 1.2) -> List[Candle]:
    closes: List[float] = []
    price = float(start)
    dir_up = True
    # Alternating ramps to create fractal highs/lows (left/right bars=5).
    for i in range(int(n)):
        closes.append(price)
        # Switch direction every 9 bars to produce clear local extrema.
        if (i + 1) % 9 == 0:
            dir_up = not dir_up
        if dir_up:
            price += float(step)
        else:
            price -= float(step * (swing / 1.2))
    return _series_from_closes(closes, wick=0.10)


def _downtrend_zigzag(*, n: int = 90, start: float = 116.0, step: float = 0.12, swing: float = 1.2) -> List[Candle]:
    closes: List[float] = []
    price = float(start)
    dir_down = True
    for i in range(int(n)):
        closes.append(price)
        if (i + 1) % 9 == 0:
            dir_down = not dir_down
        if dir_down:
            price -= float(step)
        else:
            price += float(step * (swing / 1.2))
    return _series_from_closes(closes, wick=0.10)


def fixture_smoke() -> List[Candle]:
    # A general-purpose fixture that produces swings + S/R + structure.
    return _uptrend_zigzag(n=100, start=100.0)


def fixture_structure_up() -> List[Candle]:
    closes: List[float] = []
    # Upward drift + oscillation -> produces HH and HL for structure trend.
    for i in range(100):
        phase = i % 10
        tri = (phase / 5.0) - 1.0 if phase <= 5 else 1.0 - ((phase - 5) / 5.0)
        closes.append(100.0 + i * 0.05 + tri * 0.80)
    return _series_from_closes(closes, wick=0.10)


def fixture_structure_down() -> List[Candle]:
    return _downtrend_zigzag(n=100, start=116.0)


def fixture_range_mid_nohit() -> List[Candle]:
    # Range but last close is mid (not near edges) so edge-based detectors NO_HIT.
    candles = _range_base(n=80, mid=101.0, amp=1.0)
    # force last close near mid
    last = candles[-1]
    candles[-1] = _mk_candle(t=last.time, o=last.open, h=max(last.open, 101.0) + 0.12, l=min(last.open, 101.0) - 0.12, c=101.0)
    return candles


def fixture_range_edge_buy() -> List[Candle]:
    candles = _range_base(n=80, mid=101.0, amp=1.0)
    # Force last close near the computed support with a rejection candle.
    t = candles[-1].time
    candles[-1] = _mk_candle(t=t, o=99.85, h=99.92, l=99.80, c=99.90)
    return candles


def fixture_range_edge_sell() -> List[Candle]:
    candles = _range_base(n=80, mid=101.0, amp=1.0)
    t = candles[-1].time
    # Shooting-star like candle near resistance.
    candles[-1] = _mk_candle(t=t, o=101.70, h=103.00, l=101.60, c=101.55)
    return candles


def fixture_fakeout_buy() -> List[Candle]:
    candles = _range_base(n=80, mid=101.0, amp=1.0)
    # Support ~ (min low) around 99.88. Force a pierce and close back above.
    t_prev = candles[-2].time
    t_last = candles[-1].time
    candles[-2] = _mk_candle(t=t_prev, o=100.10, h=100.30, l=98.90, c=100.00)
    candles[-1] = _mk_candle(t=t_last, o=99.95, h=100.40, l=99.20, c=100.25)
    return candles


def fixture_sr_breakout_buy() -> List[Candle]:
    # Build repeated highs near 110 to form a resistance zone, then breakout.
    closes: List[float] = []
    price = 106.0
    for i in range(70):
        if i % 14 in (12, 13):
            price = 110.0
        elif i % 14 in (6, 7):
            price = 105.5
        else:
            price = 107.5 + ((i % 7) - 3) * 0.2
        closes.append(price)
    candles = _series_from_closes(closes, wick=0.12)
    # Last candle: strong body closes above resistance zone upper.
    t = candles[-1].time
    candles[-1] = _mk_candle(t=t, o=109.6, h=111.4, l=109.4, c=111.2)
    # Ensure previous 3 highs are below zone.lower (~110*(1-0.002)=109.78)
    for j in range(2, 5):
        t2 = candles[-j].time
        candles[-j] = _mk_candle(t=t2, o=109.0, h=109.6, l=108.7, c=109.2)
    return candles


def fixture_sr_role_reversal_buy() -> List[Candle]:
    candles = fixture_sr_breakout_buy()
    # Replace last 5 candles to show breakout happened recently, then retest/hold.
    base_t = candles[-5].time
    # A breakout close above zone
    candles[-5] = _mk_candle(t=base_t, o=109.7, h=111.6, l=109.6, c=111.3)
    # Drift above
    candles[-4] = _mk_candle(t=candles[-4].time, o=111.2, h=111.5, l=110.8, c=111.1)
    candles[-3] = _mk_candle(t=candles[-3].time, o=111.1, h=111.2, l=110.6, c=110.9)
    # Retest: low near zone.upper (~110.22) and close above zone.lower (~109.78)
    candles[-2] = _mk_candle(t=candles[-2].time, o=110.9, h=111.0, l=110.15, c=110.6)
    candles[-1] = _mk_candle(t=candles[-1].time, o=110.6, h=110.8, l=110.10, c=110.7)
    return candles


def fixture_fibo_retrace_buy() -> List[Candle]:
    # Create an upswing 100 -> 110 (with the swing-low occurring inside the
    # last-80-bar lookback), then retrace to ~105 (0.5 level).
    closes: List[float] = []
    # Some pre-roll bars so the swing low isn't at the very start.
    for i in range(12):
        closes.append(104.0 + ((i % 5) - 2) * 0.10)

    # Inject a clear swing low (100) that will be included in lookback=80.
    closes.extend([103.0, 101.5, 100.0, 101.0, 102.5])

    # Push to a clear swing high at 110.0.
    n_up = 36
    for i in range(n_up):
        closes.append(102.5 + (110.0 - 102.5) * (i / (n_up - 1)))

    # Retrace down towards the 0.5 level.
    closes.extend([109.5, 108.5, 107.5, 106.5, 105.5, 105.0])

    while len(closes) < 90:
        closes.append(closes[-1] + (0.08 if (len(closes) % 6) < 3 else -0.06))

    candles = _series_from_closes(closes, wick=0.10)
    # Force last close near exact 0.5 retrace for the intended swing.
    t = candles[-1].time
    candles[-1] = _mk_candle(t=t, o=105.10, h=105.22, l=104.88, c=105.00)
    return candles


def fixture_fibo_extension_hit() -> List[Candle]:
    # Create a small-diff upswing so the computed 1.272 extension sits close to
    # the last close (within default tolerance) without requiring price to move
    # beyond the swing high.
    closes: List[float] = []
    for i in range(20):
        closes.append(100.20 + ((i % 4) - 1.5) * 0.02)

    # Clear swing low inside lookback.
    closes.extend([100.10, 100.05, 100.00, 100.08, 100.15])

    # Push to a modest swing high.
    n_up = 30
    for i in range(n_up):
        closes.append(100.15 + (100.49 - 100.15) * (i / (n_up - 1)))

    while len(closes) < 90:
        closes.append(100.45 + ((len(closes) % 6) - 3) * 0.005)

    candles = _series_from_closes(closes, wick=0.01)
    t = candles[-1].time
    candles[-1] = _mk_candle(t=t, o=100.40, h=100.51, l=100.38, c=100.49)
    return candles


def fixture_fibo_confluence_buy() -> List[Candle]:
    # Ensure the deep swing low (100) is inside the last-80-bar lookback so
    # swing/fibo primitives are available. Then create repeated touches near
    # ~105 for S/R confluence and end with a hammer-ish candle.
    closes: List[float] = []

    # Pre-roll chop.
    for i in range(12):
        closes.append(103.5 + ((i % 6) - 2.5) * 0.08)

    # Deep low inside lookback, then start the upswing.
    closes.extend([102.0, 101.0, 100.0, 101.5, 103.0])

    # Push to a clear swing high at 110.0.
    n_up = 24
    for i in range(n_up):
        closes.append(103.0 + (110.0 - 103.0) * (i / (n_up - 1)))

    # Multiple bounces to ~105.05 to build a support zone.
    for _ in range(5):
        closes.extend([108.0, 106.8, 105.05, 106.3, 107.6])

    while len(closes) < 90:
        closes.append(closes[-1] + (0.18 if (len(closes) % 8) < 4 else -0.16))

    candles = _series_from_closes(closes, wick=0.10)
    t = candles[-1].time
    # Hammer-ish near the fib 0.5 level (~105.0) with S/R proximity.
    candles[-1] = _mk_candle(t=t, o=105.05, h=105.11, l=104.65, c=105.10)
    return candles


def fixture_pinbar_hammer() -> List[Candle]:
    candles = fixture_range_mid_nohit()
    t = candles[-1].time
    candles[-1] = _mk_candle(t=t, o=101.00, h=101.05, l=99.80, c=101.08)
    return candles


def fixture_pinbar_shooting_star() -> List[Candle]:
    candles = fixture_range_mid_nohit()
    t = candles[-1].time
    candles[-1] = _mk_candle(t=t, o=101.15, h=102.20, l=101.10, c=101.00)
    return candles


def fixture_doji() -> List[Candle]:
    candles = fixture_range_mid_nohit()
    t = candles[-1].time
    candles[-1] = _mk_candle(t=t, o=101.00, h=101.60, l=100.40, c=101.02)
    return candles


def fixture_engulfing_buy() -> List[Candle]:
    candles = fixture_range_mid_nohit()
    t1 = candles[-2].time
    t2 = candles[-1].time
    # bearish then bullish engulf
    candles[-2] = _mk_candle(t=t1, o=101.20, h=101.30, l=100.70, c=100.90)
    candles[-1] = _mk_candle(t=t2, o=100.80, h=101.60, l=100.75, c=101.50)
    return candles


def fixture_engulfing_sell() -> List[Candle]:
    candles = fixture_range_mid_nohit()
    t1 = candles[-2].time
    t2 = candles[-1].time
    # bullish then bearish engulf
    candles[-2] = _mk_candle(t=t1, o=100.90, h=101.50, l=100.80, c=101.30)
    candles[-1] = _mk_candle(t=t2, o=101.40, h=101.45, l=100.60, c=100.70)
    return candles


def fixture_swing_failure_buy() -> List[Candle]:
    # Build a stable base, then create a clear lower low (fractal) near the end
    # and a bounce within the last 5 candles.
    closes: List[float] = []
    for i in range(75):
        phase = i % 10
        tri = (phase / 5.0) - 1.0 if phase <= 5 else 1.0 - ((phase - 5) / 5.0)
        closes.append(101.8 + tri * 0.20)

    # Tail: ensure a lower-low at 99.0 with >=5 candles after it.
    closes.extend(
        [
            101.7,
            101.5,
            101.3,
            101.1,
            100.9,
            100.7,
            100.5,
            100.2,
            99.0,  # lower low
            99.8,
            100.5,
            100.9,
            101.0,
            100.9,
            100.8,
        ]
    )

    candles = _series_from_closes(closes[:90], wick=0.12)
    # Make the last candle a clean bounce candle.
    candles[-1] = _mk_candle(t=candles[-1].time, o=100.6, h=101.0, l=100.4, c=100.8)
    return candles


_FIXTURES: Dict[str, Callable[[], List[Candle]]] = {
    "smoke": fixture_smoke,
    "structure_up": fixture_structure_up,
    "structure_down": fixture_structure_down,
    "range_mid_nohit": fixture_range_mid_nohit,
    "range_edge_buy": fixture_range_edge_buy,
    "range_edge_sell": fixture_range_edge_sell,
    "fakeout_buy": fixture_fakeout_buy,
    "sr_breakout_buy": fixture_sr_breakout_buy,
    "sr_role_reversal_buy": fixture_sr_role_reversal_buy,
    "fibo_retrace_buy": fixture_fibo_retrace_buy,
    "fibo_extension_hit": fixture_fibo_extension_hit,
    "fibo_confluence_buy": fixture_fibo_confluence_buy,
    "pinbar_hammer": fixture_pinbar_hammer,
    "pinbar_shooting_star": fixture_pinbar_shooting_star,
    "doji": fixture_doji,
    "engulfing_buy": fixture_engulfing_buy,
    "engulfing_sell": fixture_engulfing_sell,
    "swing_failure_buy": fixture_swing_failure_buy,
}


def list_fixtures() -> List[str]:
    return sorted(list(_FIXTURES.keys()))


def load_candles(fixture_id: str) -> List[Candle]:
    fid = str(fixture_id or "").strip()
    if fid not in _FIXTURES:
        raise KeyError(f"Unknown fixture_id: {fid}")
    candles = _FIXTURES[fid]()
    if not isinstance(candles, list) or not candles:
        raise ValueError(f"Fixture returned empty list: {fid}")
    return candles
