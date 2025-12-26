"""tests.test_cooldown_strategy_scoped

Step 9: Strategy-scoped cooldown.

Requirement:
- state key is scoped by (symbol, tf, strategy_id, direction)
- if one strategy is in cooldown, another strategy_id should not be blocked

Run:
    pytest -q
"""

from __future__ import annotations


def test_cooldown_is_strategy_scoped(tmp_path):
    from scanner_state import SignalStateStore

    store = SignalStateStore(path=str(tmp_path / "signal_state.json"))

    ts0 = 1_700_000_000.0
    cooldown_min = 30

    k1 = SignalStateStore.make_key(symbol="EURUSD", timeframe="M15", strategy_id="stratA", direction="BUY")
    k2 = SignalStateStore.make_key(symbol="EURUSD", timeframe="M15", strategy_id="stratB", direction="BUY")

    store.record_sent(k1, ts0, "EURUSD", direction="BUY", timeframe="M15", strategy_id="stratA")

    # Same strategy+tf+direction => blocked within cooldown
    assert store.can_send(k1, ts0 + 60, cooldown_minutes=cooldown_min) is False

    # Different strategy_id => should not be blocked
    assert store.can_send(k2, ts0 + 60, cooldown_minutes=cooldown_min) is True


def test_daily_limit_is_strategy_scoped(tmp_path):
    from scanner_state import SignalStateStore

    store = SignalStateStore(path=str(tmp_path / "signal_state.json"))

    day = "2025-12-23"
    # strategy A hits limit, strategy B remains independent
    for _ in range(5):
        store.increment_daily("EURUSD", "M15", "stratA", day)

    assert store.get_daily_count("EURUSD", "M15", "stratA", day) == 5
    assert store.get_daily_count("EURUSD", "M15", "stratB", day) == 0
