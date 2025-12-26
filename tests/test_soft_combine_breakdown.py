from __future__ import annotations

import math

from core.models import DetectorHit


def _mk(detector: str, family: str, direction: str, base: float, reasons=None):
    return DetectorHit(
        detector=detector,
        family=family,
        direction=direction,  # type: ignore[arg-type]
        score_contrib=base,
        reasons=list(reasons or []),
        evidence={"family": family},
    )


def test_breakdown_sums_match_final_score():
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec

    spec = StrategySpec(
        strategy_id="s1",
        enabled=True,
        min_score=0.0,
        min_rr=0.0,
        allowed_regimes=["RANGE"],
        detectors=[],
        detector_weights={"d1": 2.0},
        family_weights={"sr": 1.5},
        conflict_epsilon=0.05,
        confluence_bonus_per_family=0.25,
        max_top_hits=3,
    )

    hits = [
        _mk("d1", "sr", "BUY", 1.0),
        _mk("d2", "range", "BUY", 0.5),
        _mk("d3", "sr", "SELL", 0.6),
    ]

    res = combine(hits, spec, "RANGE")
    assert res.ok
    bd = res.evidence.get("score_breakdown")
    assert isinstance(bd, dict)

    # Winner should be BUY
    assert bd.get("final_direction") == "BUY"

    buy_weighted = float(bd.get("buy_score_weighted") or 0.0)
    buy_bonus = float(bd.get("confluence_bonus_buy") or 0.0)
    final = float(bd.get("final_score") or 0.0)

    assert math.isclose(final, buy_weighted + buy_bonus, rel_tol=1e-9, abs_tol=1e-9)


def test_bonus_applied_correctly_per_unique_family():
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec

    spec = StrategySpec(
        strategy_id="s1",
        enabled=True,
        min_score=0.0,
        min_rr=0.0,
        allowed_regimes=["RANGE"],
        detectors=[],
        detector_weights={},
        family_weights={},
        conflict_epsilon=0.05,
        confluence_bonus_per_family=0.25,
        max_top_hits=3,
    )

    # BUY has two unique families => +0.25; SELL has one => +0
    hits = [
        _mk("d1", "sr", "BUY", 1.0),
        _mk("d2", "range", "BUY", 1.0),
        _mk("d3", "sr", "SELL", 1.8),
    ]

    res = combine(hits, spec, "RANGE")
    bd = res.evidence.get("score_breakdown")
    assert isinstance(bd, dict)
    assert math.isclose(float(bd.get("confluence_bonus_buy") or 0.0), 0.25, abs_tol=1e-12)
    assert math.isclose(float(bd.get("confluence_bonus_sell") or 0.0), 0.0, abs_tol=1e-12)


def test_top_contribs_sorted_desc():
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec

    spec = StrategySpec(
        strategy_id="s1",
        enabled=True,
        min_score=0.0,
        min_rr=0.0,
        allowed_regimes=["RANGE"],
        detectors=[],
        detector_weights={"d1": 1.0, "d2": 1.0, "d3": 1.0},
        family_weights={},
        conflict_epsilon=0.05,
        confluence_bonus_per_family=0.0,
        max_top_hits=3,
    )

    hits = [
        _mk("d1", "sr", "BUY", 0.1),
        _mk("d2", "sr", "BUY", 0.9),
        _mk("d3", "sr", "BUY", 0.5),
    ]

    res = combine(hits, spec, "RANGE")
    bd = res.evidence.get("score_breakdown")
    assert isinstance(bd, dict)
    top = bd.get("top_hit_contribs")
    assert isinstance(top, list)
    assert [t.get("detector") for t in top] == ["d2", "d3", "d1"]


def test_pair_none_near_miss_includes_top_contribs_fields():
    from scoring.soft_combine import combine
    from strategies.strategy_spec import StrategySpec
    from scanner_service import _extract_score_breakdown_fields_for_logs

    spec = StrategySpec(
        strategy_id="s1",
        enabled=True,
        min_score=10.0,
        min_rr=0.0,
        allowed_regimes=["RANGE"],
        detectors=[],
        detector_weights={},
        family_weights={},
        conflict_epsilon=0.05,
        confluence_bonus_per_family=0.0,
        max_top_hits=3,
    )

    hits = [
        _mk("d1", "sr", "BUY", 1.0),
        _mk("d2", "sr", "BUY", 0.5),
        _mk("d3", "sr", "SELL", 0.1),
    ]

    res = combine(hits, spec, "RANGE")
    assert not res.ok
    dbg = {"score_breakdown": res.evidence.get("score_breakdown")}

    fields = _extract_score_breakdown_fields_for_logs(dbg)
    assert "top_contribs" in fields
    assert "score_raw" in fields
    assert "bonus" in fields
