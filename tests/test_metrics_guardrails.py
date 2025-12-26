from __future__ import annotations

from metrics.guardrails import evaluate_guardrails


def test_guardrails_trigger_ok_rate() -> None:
    summary = {
        "date": "2099-01-01",
        "total_pairs": 100,
        "ok_count": 10,
        "ok_rate": 0.10,
        "avg_rr": 2.0,
        "cooldown_blocks": 0,
        "top_reasons": [{"reason": "NO_HITS", "count": 90}],
        "top_strategies_by_ok": [{"strategy_id": "s1", "ok_count": 10}],
    }
    alerts = evaluate_guardrails(summary)
    assert any(a.code == "OK_RATE_LOW" for a in alerts)


def test_guardrails_trigger_avg_rr() -> None:
    summary = {
        "date": "2099-01-01",
        "total_pairs": 10,
        "ok_count": 10,
        "ok_rate": 1.0,
        "avg_rr": 1.2,
        "cooldown_blocks": 0,
        "top_reasons": [],
        "top_strategies_by_ok": [{"strategy_id": "s1", "ok_count": 10}],
    }
    alerts = evaluate_guardrails(summary)
    assert any(a.code == "AVG_RR_LOW" for a in alerts)


def test_guardrails_trigger_no_hits_dominance() -> None:
    # total=100 ok=30 => none_total=70, NO_HITS count=60 => 85.7% > 60%
    summary = {
        "date": "2099-01-01",
        "total_pairs": 100,
        "ok_count": 30,
        "ok_rate": 0.30,
        "avg_rr": 2.0,
        "cooldown_blocks": 0,
        "top_reasons": [{"reason": "NO_HITS", "count": 60}],
        "top_strategies_by_ok": [{"strategy_id": "s1", "ok_count": 30}],
    }
    alerts = evaluate_guardrails(summary)
    assert any(a.code == "TOP_REASON_DOMINANCE" for a in alerts)


def test_guardrails_no_alert_when_within_threshold() -> None:
    summary = {
        "date": "2099-01-01",
        "total_pairs": 100,
        "ok_count": 50,
        "ok_rate": 0.50,
        "avg_rr": 2.0,
        "cooldown_blocks": 2,
        "top_reasons": [{"reason": "NO_HITS", "count": 20}],
        "top_strategies_by_ok": [{"strategy_id": "s1", "ok_count": 50}],
    }
    alerts = evaluate_guardrails(summary)
    assert alerts == []
