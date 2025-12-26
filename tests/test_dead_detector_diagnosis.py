from __future__ import annotations

from metrics.dead_detector_diagnosis import compact_dead_diagnosis, diagnose_dead_detectors


def test_not_in_any_strategy_cause() -> None:
    dead = ["fibo_retrace"]
    strategies = [
        {
            "strategy_id": "s1",
            "enabled": True,
            "allowed_regimes": ["TREND_BULL"],
            "detectors": ["sr_bounce"],
            "detector_params": {},
        }
    ]
    registry_meta = {"fibo_retrace": {"supported_regimes": ["TREND_BULL", "TREND_BEAR"]}}

    res = diagnose_dead_detectors(dead, strategies, registry_meta, window_stats={"window_hours": 24})
    assert "fibo_retrace" in res
    assert "NOT_IN_ANY_STRATEGY" in (res["fibo_retrace"].get("likely_causes") or [])


def test_regime_mismatch_cause() -> None:
    dead = ["sweep_liquidity"]
    strategies = [
        {
            "strategy_id": "s1",
            "enabled": True,
            "allowed_regimes": ["RANGE"],
            "detectors": ["sweep_liquidity"],
            "detector_params": {},
        }
    ]
    registry_meta = {"sweep_liquidity": {"supported_regimes": ["TREND_BULL", "TREND_BEAR"]}}

    res = diagnose_dead_detectors(dead, strategies, registry_meta, window_stats={"window_hours": 24})
    assert "sweep_liquidity" in res
    assert "REGIME_MISMATCH" in (res["sweep_liquidity"].get("likely_causes") or [])


def test_compact_diagnosis_limits() -> None:
    details = {
        f"d{i}": {"likely_causes": ["NOT_IN_ANY_STRATEGY"], "suggestions": ["x"]}
        for i in range(10)
    }
    compact = compact_dead_diagnosis(details, limit=5)
    assert isinstance(compact, dict)
    assert len(compact) == 5
    # Deterministic ordering by detector name
    assert list(compact.keys()) == ["d0", "d1", "d2", "d3", "d4"]
