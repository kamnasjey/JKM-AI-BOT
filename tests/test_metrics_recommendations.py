from __future__ import annotations

from metrics.alert_codes import AVG_RR_LOW, OK_RATE_LOW
from metrics.recommendations import format_tuning_suggestions, generate_recommendations


def _base_summary(*, top_reason: str) -> dict:
    return {
        "date": "2099-01-01",
        "window_hours": 24,
        "total_pairs": 100,
        "ok_count": 10,
        "ok_rate": 0.10,
        "top_reasons": [{"reason": top_reason, "count": 50}],
        "top_strategies_by_ok": [],
        "avg_score": None,
        "avg_rr": 1.2,
        "cooldown_blocks": 0,
        "daily_limit_blocks": 0,
        "regimes": [],
    }


def test_reco_no_hits_rule() -> None:
    summary = _base_summary(top_reason="NO_HITS")
    recos = generate_recommendations(summary, alert_codes=[OK_RATE_LOW])
    assert any(r.code == "RECO_OK_RATE_LOW_NO_HITS" for r in recos)


def test_reco_score_below_min_rule() -> None:
    summary = _base_summary(top_reason="SCORE_BELOW_MIN")
    recos = generate_recommendations(summary, alert_codes=[OK_RATE_LOW])
    assert any(r.code == "RECO_OK_RATE_LOW_SCORE_BELOW_MIN" for r in recos)


def test_reco_avg_rr_low_rule() -> None:
    summary = _base_summary(top_reason="NO_HITS")
    recos = generate_recommendations(summary, alert_codes=[AVG_RR_LOW])
    assert any(r.code == "RECO_AVG_RR_LOW" for r in recos)


def test_report_contains_top3() -> None:
    summary = _base_summary(top_reason="NO_HITS")
    recos = generate_recommendations(summary, alert_codes=[OK_RATE_LOW, AVG_RR_LOW])
    # Add extra synthetic recommendation to ensure truncation works
    from metrics.recommendations import Recommendation

    recos.append(Recommendation(code="RECO_ZZZ", priority=99, message="extra", actions=[]))

    msg = format_tuning_suggestions(date="2099-01-01", recommendations=recos, max_items=3)
    assert msg.startswith("🛠 Tuning Suggestions (2099-01-01):")
    assert "1)" in msg
    assert "2)" in msg
    assert "3)" in msg
    assert "4)" not in msg
