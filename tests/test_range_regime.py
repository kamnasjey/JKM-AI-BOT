from __future__ import annotations

from datetime import datetime, timedelta, timezone

from engine_blocks import Candle
from core.user_core_engine import scan_pair_cached_indicator_free


def _make_range_candles(n: int = 140) -> list[Candle]:
    """Create candles that form a visible range box."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles: list[Candle] = []

    support = 1.0000
    resistance = 1.0100

    for i in range(n):
        t = start + timedelta(minutes=5 * i)
        # Oscillate between support and resistance
        phase = i % 20
        if phase < 10:
            price = support + (resistance - support) * (phase / 10.0)
        else:
            price = resistance - (resistance - support) * ((phase - 10) / 10.0)

        # Make the last candle finish near support
        if i == n - 1:
            price = support * 1.0003

        open_p = price
        close_p = price
        high_p = price + 0.0004
        low_p = price - 0.0004

        candles.append(Candle(time=t, open=open_p, high=high_p, low=low_p, close=close_p))

    return candles


def test_range_regime_allows_range_safe_detectors_when_unrequired() -> None:
    candles = _make_range_candles()

    # Force structure trend to be "unclear" by making fractal windows too large
    # so no fractal swings are produced => structure_valid False.
    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 1.2,
        "engine_version": "indicator_free_v1",
        "require_clear_trend_for_signal": False,
        "detectors": {"range_box_edge": {"enabled": True}},
        "primitives_config": {"fractal_left_bars": 90, "fractal_right_bars": 90},
    }

    res = scan_pair_cached_indicator_free("EURUSD", profile, candles, candles[-120:])

    assert any(r == "TREND_UNCLEAR_REGIME_FALLBACK" for r in res.reasons)
    assert any(r == "REGIME|CHOP" or r == "REGIME|RANGE" for r in res.reasons)
    assert res.has_setup is True
    assert any(r.startswith("DETECTOR|") for r in res.reasons)
    assert any("range_box_edge" in r for r in res.reasons if r.startswith("DETECTOR|"))


def test_range_regime_blocks_signals_when_require_clear_trend_true() -> None:
    candles = _make_range_candles()

    profile = {
        "trend_tf": "H4",
        "entry_tf": "M15",
        "min_rr": 1.2,
        "engine_version": "indicator_free_v1",
        "require_clear_trend_for_signal": True,
        "detectors": {"range_box_edge": {"enabled": True}},
        "primitives_config": {"fractal_left_bars": 90, "fractal_right_bars": 90},
    }

    res = scan_pair_cached_indicator_free("EURUSD", profile, candles, candles[-120:])

    assert res.has_setup is False
    assert res.reasons and res.reasons[0] == "TREND_UNCLEAR_REGIME_FALLBACK"
