from engine.utils.reason_codes import build_governance_evidence


def test_governance_evidence_has_all_keys_and_na_safe():
    ev = build_governance_evidence(strategy_id=None, symbol=None, tf=None, direction=None)
    assert set(ev.keys()) == {
        "strategy_id",
        "symbol",
        "tf",
        "direction",
        "last_sent_ts",
        "cooldown_minutes",
        "cooldown_remaining_s",
        "sent_today_count",
        "daily_limit",
    }
    assert ev["strategy_id"] == "NA"
    assert ev["symbol"] == "NA"
    assert ev["tf"] == "NA"
    assert ev["direction"] == "NA"


def test_governance_evidence_preserves_values():
    ev = build_governance_evidence(
        strategy_id="s1",
        symbol="eurusd",
        tf="m15",
        direction="buy",
        last_sent_ts=123.0,
        cooldown_minutes=30,
        cooldown_remaining_s=12.5,
        sent_today_count=3,
        daily_limit=10,
    )
    assert ev["strategy_id"] == "s1"
    assert ev["symbol"] == "EURUSD"
    assert ev["tf"] == "M15"
    assert ev["direction"] == "BUY"
    assert ev["last_sent_ts"] == 123.0
    assert ev["cooldown_minutes"] == 30
    assert ev["cooldown_remaining_s"] == 12.5
    assert ev["sent_today_count"] == 3
    assert ev["daily_limit"] == 10
