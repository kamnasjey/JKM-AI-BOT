"""tests.test_soft_combine_weights

Step 6: soft_combine StrategySpec weighting/conflict behavior.

Validates:
- detector_weights and family_weights affect aggregated score
- conflict uses <= conflict_epsilon (edge-inclusive)

Run:
    pytest -q
"""

from __future__ import annotations


def test_weights_affect_score():
    from core.models import DetectorHit
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec

    hits = [
        DetectorHit(detector="a", direction="BUY", score_contrib=1.0, family="sr"),
        DetectorHit(detector="b", direction="BUY", score_contrib=1.0, family="sr"),
    ]

    spec1 = StrategySpec(
        strategy_id="w1",
        enabled=True,
        min_score=0.0,
        min_rr=0.0,
        allowed_regimes=["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"],
        detectors=[],
        detector_weights={},
        family_weights={},
        conflict_epsilon=0.01,
        confluence_bonus_per_family=0.0,
        max_top_hits=3,
    )

    spec2 = StrategySpec(
        strategy_id="w2",
        enabled=True,
        min_score=0.0,
        min_rr=0.0,
        allowed_regimes=["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"],
        detectors=[],
        detector_weights={"a": 2.0},
        family_weights={"sr": 1.5},
        conflict_epsilon=0.01,
        confluence_bonus_per_family=0.0,
        max_top_hits=3,
    )

    r1 = combine(hits, spec1, "RANGE")
    r2 = combine(hits, spec2, "RANGE")

    assert float(r2.evidence.get("buy_score")) > float(r1.evidence.get("buy_score"))


def test_conflict_epsilon_is_inclusive():
    from core.models import DetectorHit
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec

    hits = [
        DetectorHit(detector="buy", direction="BUY", score_contrib=1.00, family="sr"),
        DetectorHit(detector="sell", direction="SELL", score_contrib=1.05, family="range"),
    ]

    spec = StrategySpec(
        strategy_id="c",
        enabled=True,
        min_score=1.0,
        min_rr=0.0,
        allowed_regimes=["TREND_BULL", "TREND_BEAR", "RANGE", "CHOP"],
        detectors=[],
        detector_weights={},
        family_weights={},
        conflict_epsilon=0.05,
        confluence_bonus_per_family=0.0,
        max_top_hits=3,
    )

    res = combine(hits, spec, "RANGE")
    assert res.ok is False
    assert res.fail_reason == "CONFLICT_SCORE"
