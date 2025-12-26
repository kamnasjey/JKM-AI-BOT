from user_profile import parse_str_command


def test_parse_str_command_examples():
    out = parse_str_command("STR: risk=2.5 trend=H1")
    assert out["risk_percent"] == 2.5
    assert out["trend_tf"] == "H1"

    out = parse_str_command("STR: exclude XAUUSD, GBPJPY")
    assert out["exclude_pairs"] == ["XAUUSD", "GBPJPY"]

    out = parse_str_command('STR: {"min_rr": 5, "note": "JSON mode"}')
    assert out["min_rr"] == 5
    assert out["note"] == "JSON mode"

    out = parse_str_command("STR: watch EURUSD, USDJPY entry=M5")
    assert out["watch_pairs"] == ["EURUSD", "USDJPY"]
    assert out["entry_tf"] == "M5"
