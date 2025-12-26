from __future__ import annotations

from data_readiness import readiness_check


class _FakeCache:
    def __init__(self, *, m5: int, m15: int, h4: int):
        self._m5 = m5
        self._m15 = m15
        self._h4 = h4

    def get_candles(self, symbol: str):
        return [object()] * self._m5

    def get_resampled(self, symbol: str, tf: str):
        t = str(tf).upper()
        if t == "M15":
            return [object()] * self._m15
        if t == "H4":
            return [object()] * self._h4
        return []


def test_readiness_true_with_defaults_example():
    cache = _FakeCache(m5=5000, m15=1001, h4=64)
    ready, reason, details = readiness_check(
        cache,
        symbol="XAUUSD",
        trend_tf="H4",
        entry_tf="M15",
        min_trend_bars=55,
        min_entry_bars=200,
    )
    assert ready is True
    assert reason == "ok"
    assert "coverage" in details


def test_readiness_defaults_when_none_inputs():
    cache = _FakeCache(m5=5000, m15=1001, h4=64)
    ready, reason, details = readiness_check(
        cache,
        symbol="XAUUSD",
        trend_tf="H4",
        entry_tf="M15",
        min_trend_bars=None,
        min_entry_bars=None,
    )
    assert ready is True
    assert reason == "ok"
