import json

from scanner_state import SignalStateStore


def test_state_load_legacy_entries_treated_as_legacy_strategy_id(tmp_path):
    state_path = tmp_path / "signal_state.json"

    legacy = {
        "schema": 1,
        # Older key format: SYMBOL|TF|DIRECTION (no strategy_id)
        "sent": {
            "EURUSD|M15|BUY": {
                "ts": 1730000000.0,
                "symbol": "EURUSD",
                "direction": "BUY",
                "timeframe": "M15",
            }
        },
        # Older daily bucket: SYMBOL|TF (no strategy_id)
        "daily": {"EURUSD|M15": {"2025-12-20": 2}},
    }

    state_path.write_text(json.dumps(legacy), encoding="utf-8")

    store = SignalStateStore(path=str(state_path))
    store.load()

    # sent: should migrate to SYMBOL|TF|legacy|DIRECTION
    migrated_key = store.make_key(symbol="EURUSD", timeframe="M15", strategy_id="legacy", direction="BUY")
    rec = store.get_sent_record(migrated_key)
    assert rec is not None
    assert rec.strategy_id == "legacy"
    assert rec.timeframe == "M15"
    assert rec.direction == "BUY"

    # daily: should migrate to SYMBOL|TF|legacy bucket
    assert store.get_daily_count("EURUSD", "M15", "legacy", "2025-12-20") == 2
