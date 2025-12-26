"""tests.test_soft_combine_m3

M3: soft_combine aggregation/confluence/conflict.

Run:
    python -m pytest -q
"""

from __future__ import annotations


def test_hits_aggregation_and_direction_choice():
    from core.models import DetectorHit
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec

    hits = [
        DetectorHit(detector="range_box_edge", direction="BUY", score_contrib=0.60, family="range"),
        DetectorHit(detector="sr_bounce", direction="BUY", score_contrib=0.55, family="sr"),
        DetectorHit(detector="doji", direction="SELL", score_contrib=0.30, family="pattern"),
    ]

    # BUY total = 0.60 + 0.55 + confluence(2 families => +0.25) = 1.40
    spec = StrategySpec(
        strategy_id="t",
        enabled=True,
        min_score=1.0,
        min_rr=0.0,
        allowed_regimes=["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"],
        detectors=[],
        detector_weights={},
        family_weights={},
        conflict_epsilon=0.15,
        confluence_bonus_per_family=0.25,
        max_top_hits=3,
    )
    res = combine(hits, spec, "RANGE")

    assert res.ok is True
    assert res.direction == "BUY"
    assert float(res.evidence.get("buy_score")) >= 1.39
    assert res.evidence.get("direction") == "BUY"


def test_confluence_bonus_unique_families():
    from core.models import DetectorHit
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec

    hits = [
        DetectorHit(detector="a", direction="BUY", score_contrib=0.40, family="range"),
        DetectorHit(detector="b", direction="BUY", score_contrib=0.40, family="sr"),
        DetectorHit(detector="c", direction="BUY", score_contrib=0.40, family="pattern"),
    ]

    # 3 unique families => bonus = 0.25*(3-1)=0.50
    spec = StrategySpec(
        strategy_id="t",
        enabled=True,
        min_score=1.0,
        min_rr=0.0,
        allowed_regimes=["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"],
        detectors=[],
        detector_weights={},
        family_weights={},
        conflict_epsilon=0.15,
        confluence_bonus_per_family=0.25,
        max_top_hits=3,
    )
    res = combine(hits, spec, "RANGE")

    assert res.ok is True
    assert res.direction == "BUY"
    assert abs(float(res.evidence.get("buy_score")) - (0.40 + 0.40 + 0.40 + 0.50)) < 1e-9


def test_conflict_resolution_when_both_above_min_and_diff_small():
    from core.models import DetectorHit
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec

    hits = [
        DetectorHit(detector="buy1", direction="BUY", score_contrib=1.00, family="sr"),
        DetectorHit(detector="sell1", direction="SELL", score_contrib=1.05, family="range"),
    ]

    spec = StrategySpec(
        strategy_id="t",
        enabled=True,
        min_score=1.0,
        min_rr=0.0,
        allowed_regimes=["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"],
        detectors=[],
        detector_weights={},
        family_weights={},
        conflict_epsilon=0.10,
        confluence_bonus_per_family=0.25,
        max_top_hits=3,
    )
    res = combine(hits, spec, "RANGE")

    assert res.ok is False
    assert res.fail_reason == "CONFLICT_SCORE"
