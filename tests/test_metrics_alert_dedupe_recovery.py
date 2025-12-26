from __future__ import annotations

import json

from metrics.guardrails import process_guardrails_stateful


def test_alert_dedupe_repeat_no_notify(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("METRICS_ALERT_REPEAT_NOTIFY", "0")

    state_path = str(tmp_path / "alert_state.json")

    # Day 1: trigger
    summary_day1 = {
        "date": "2099-01-01",
        "total_pairs": 100,
        "ok_count": 10,
        "ok_rate": 0.10,
        "avg_rr": 2.0,
        "cooldown_blocks": 0,
        "top_reasons": [],
        "top_strategies_by_ok": [],
    }
    res1 = process_guardrails_stateful(summary_day1, state_path=state_path)
    assert len(res1["trigger"]) >= 1

    # Day 2: still trigger => repeat (no notify)
    summary_day2 = dict(summary_day1)
    summary_day2["date"] = "2099-01-02"
    res2 = process_guardrails_stateful(summary_day2, state_path=state_path)

    # Because alert is already active and repeat notify is off,
    # we expect no new trigger notifications.
    assert res2["trigger"] == []
    assert len(res2["repeat"]) >= 1


def test_alert_recovery_sends_message(tmp_path) -> None:
    state_path = str(tmp_path / "alert_state.json")

    # Trigger first
    summary_bad = {
        "date": "2099-01-01",
        "total_pairs": 100,
        "ok_count": 10,
        "ok_rate": 0.10,
        "avg_rr": 2.0,
        "cooldown_blocks": 0,
        "top_reasons": [],
        "top_strategies_by_ok": [],
    }
    res1 = process_guardrails_stateful(summary_bad, state_path=state_path)
    assert len(res1["trigger"]) >= 1

    # Recover next day
    summary_good = dict(summary_bad)
    summary_good["date"] = "2099-01-02"
    summary_good["ok_rate"] = 0.50
    summary_good["ok_count"] = 50
    res2 = process_guardrails_stateful(summary_good, state_path=state_path)

    assert res2["trigger"] == []
    assert res2["repeat"] == []
    assert len(res2["recover"]) >= 1
    assert "Recovered" in str(res2["recover"][0]["message"])


def test_state_persisted_atomic(tmp_path) -> None:
    state_path = str(tmp_path / "alert_state.json")

    summary = {
        "date": "2099-01-01",
        "total_pairs": 100,
        "ok_count": 10,
        "ok_rate": 0.10,
        "avg_rr": 2.0,
        "cooldown_blocks": 0,
        "top_reasons": [],
        "top_strategies_by_ok": [],
    }
    process_guardrails_stateful(summary, state_path=state_path)

    # File exists and is valid JSON
    raw = (tmp_path / "alert_state.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data.get("schema") == 1
    assert isinstance(data.get("alerts"), dict)

    # Temp file should not remain
    assert not (tmp_path / "alert_state.json.tmp").exists()
