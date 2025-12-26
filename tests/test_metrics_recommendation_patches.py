from __future__ import annotations

from metrics.alert_codes import OK_RATE_LOW
from metrics.recommendations import build_patch_preview, generate_recommendations


def _strategies_json(min_score: float) -> dict:
    return {
        "schema_version": 1,
        "include_presets": [],
        "strategies": [
            {
                "strategy_id": "s1",
                "enabled": True,
                "priority": 50,
                "min_score": float(min_score),
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": ["range_box_edge", "sr_bounce"],
                "confluence_bonus_per_family": 0.25,
            }
        ],
    }


def _summary(top_reason: str) -> dict:
    return {
        "date": "2099-01-01",
        "window_hours": 24,
        "total_pairs": 100,
        "ok_count": 10,
        "ok_rate": 0.10,
        "top_reasons": [{"reason": top_reason, "count": 50}],
        "top_strategies_by_ok": [{"strategy_id": "s1", "ok_count": 10}],
        "avg_score": None,
        "avg_rr": 2.0,
        "cooldown_blocks": 0,
        "daily_limit_blocks": 0,
        "regimes": [{"regime": "RANGE", "count": 80}],
    }


def test_actions_generated_for_no_hits() -> None:
    summary = _summary("NO_HITS")
    sj = _strategies_json(min_score=1.0)

    recos = generate_recommendations(summary, alert_codes=[OK_RATE_LOW], strategies_json=sj)
    r = next(x for x in recos if x.code == "RECO_OK_RATE_LOW_NO_HITS")
    assert len(r.actions) >= 1
    a = r.actions[0]
    assert a.type == "edit_strategy"
    assert a.strategy_id == "s1"
    assert "min_score" in a.changes or "allowed_regimes" in a.changes or "detectors" in a.changes


def test_patch_preview_contains_before_after() -> None:
    summary = _summary("NO_HITS")
    sj = _strategies_json(min_score=1.0)

    recos = generate_recommendations(summary, alert_codes=[OK_RATE_LOW], strategies_json=sj)
    r = next(x for x in recos if x.code == "RECO_OK_RATE_LOW_NO_HITS")
    preview = build_patch_preview(sj, list(r.actions))
    assert "before:" in preview
    assert "after:" in preview
    assert "strategy=s1" in preview


def test_bounds_for_min_score() -> None:
    summary = _summary("SCORE_BELOW_MIN")
    sj = _strategies_json(min_score=0.55)

    recos = generate_recommendations(summary, alert_codes=[OK_RATE_LOW], strategies_json=sj)
    r = next(x for x in recos if x.code == "RECO_OK_RATE_LOW_SCORE_BELOW_MIN")
    assert r.actions
    a = r.actions[0]
    ms = a.changes.get("min_score") or {}
    assert float(ms.get("to")) >= 0.5
