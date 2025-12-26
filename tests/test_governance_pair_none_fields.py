from engine.utils.reason_codes import build_governance_evidence


def test_governance_pair_none_defaults_sent_today_count_to_zero():
    ev = build_governance_evidence(strategy_id="A", symbol="EURUSD", tf="M15", direction="BUY")
    assert ev["sent_today_count"] == 0
    # still NA-safe for other missing fields
    assert ev["last_sent_ts"] == "NA"
    assert ev["cooldown_remaining_s"] == "NA"
