from datetime import datetime, timedelta

from engine_blocks import Candle, find_last_swing, check_fibo_retrace_zone


def _mk_candle(t: datetime, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(time=t, open=o, high=h, low=l, close=c)


def test_find_last_swing_up_chronological():
    # Lowest low occurs, then later highest high
    t0 = datetime(2025, 1, 1)
    candles = [
        _mk_candle(t0 + timedelta(minutes=i), 10, 11 + i * 0.1, 9 + i * 0.1, 10) for i in range(10)
    ]
    # Force a deep low at i=2 and a later high at i=8
    candles[2] = _mk_candle(t0 + timedelta(minutes=2), 10, 10.5, 5.0, 9.5)
    candles[8] = _mk_candle(t0 + timedelta(minutes=8), 10, 20.0, 9.0, 19.0)

    swing = find_last_swing(candles, lookback=10, direction="up")
    assert swing is not None
    assert swing.low == 5.0
    assert swing.high == 20.0


def test_find_last_swing_down_chronological():
    # Highest high occurs, then later lowest low
    t0 = datetime(2025, 1, 1)
    candles = [
        _mk_candle(t0 + timedelta(minutes=i), 10, 11, 9, 10) for i in range(10)
    ]
    candles[1] = _mk_candle(t0 + timedelta(minutes=1), 10, 50.0, 9.0, 12.0)
    candles[7] = _mk_candle(t0 + timedelta(minutes=7), 10, 11.0, 3.0, 4.0)

    swing = find_last_swing(candles, lookback=10, direction="down")
    assert swing is not None
    assert swing.high == 50.0
    assert swing.low == 3.0


def test_fibo_zone_direction_up_vs_down():
    t0 = datetime(2025, 1, 1)
    # Simple candles with last_close to test in-zone logic
    candles = [_mk_candle(t0, 0, 0, 0, 0)]
    swing = type("S", (), {"low": 100.0, "high": 200.0})()

    # Up: 0.5-0.618 zone is 150-161.8
    candles[-1] = _mk_candle(t0, 0, 0, 0, 155.0)
    info_up = check_fibo_retrace_zone(candles, swing, (0.5, 0.618), direction="up")
    assert info_up.in_zone is True

    # Down: 0.5-0.618 zone from high is 150-138.2 (zone_low=138.2, zone_high=150)
    candles[-1] = _mk_candle(t0, 0, 0, 0, 140.0)
    info_down = check_fibo_retrace_zone(candles, swing, (0.5, 0.618), direction="down")
    assert info_down.in_zone is True
