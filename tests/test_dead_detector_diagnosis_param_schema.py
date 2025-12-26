from __future__ import annotations


from metrics.dead_detector_diagnosis import diagnose_dead_detectors


def test_params_invalid_out_of_range_detected_via_schema() -> None:
    details = diagnose_dead_detectors(
        dead_list=["sr_bounce"],
        strategies_specs=[
            {
                "strategy_id": "s1",
                "enabled": True,
                "allowed_regimes": ["RANGE"],
                "detectors": ["sr_bounce"],
                "detector_params": {"sr_bounce": {"touch_tolerance": -1}},
            }
        ],
        registry_meta={
            "sr_bounce": {
                "supported_regimes": ["RANGE"],
                "family": "sr",
                "param_schema": {
                    "touch_tolerance": {"type": "float", "min": 0.00005, "max": 0.01, "strict_low": 0.0005},
                },
            }
        },
        window_stats=None,
    )

    row = details.get("sr_bounce") or {}
    assert "PARAMS_INVALID" in (row.get("likely_causes") or [])

    sugg = row.get("suggestions") or []
    assert any("touch_tolerance" in s and "-1" in s for s in sugg)


def test_params_too_strict_detected_from_family_params() -> None:
    details = diagnose_dead_detectors(
        dead_list=["sr_bounce"],
        strategies_specs=[
            {
                "strategy_id": "s1",
                "enabled": True,
                "allowed_regimes": ["RANGE"],
                "detectors": ["sr_bounce"],
                "family_params": {"sr": {"touch_tolerance": 0.0001}},
                "detector_params": {},
            }
        ],
        registry_meta={
            "sr_bounce": {
                "supported_regimes": ["RANGE"],
                "family": "sr",
                "param_schema": {
                    "touch_tolerance": {"type": "float", "min": 0.00005, "max": 0.01, "strict_low": 0.0005},
                },
            }
        },
        window_stats=None,
    )

    row = details.get("sr_bounce") or {}
    assert "PARAMS_TOO_STRICT" in (row.get("likely_causes") or [])

    sugg = row.get("suggestions") or []
    # Must include exact param key/value and a safe bound.
    assert any("touch_tolerance=0.0001" in s and "0.0005" in s for s in sugg)


def test_no_schema_no_params_false_positives() -> None:
    details = diagnose_dead_detectors(
        dead_list=["sr_breakout"],
        strategies_specs=[
            {
                "strategy_id": "s1",
                "enabled": True,
                "allowed_regimes": ["RANGE"],
                "detectors": ["sr_breakout"],
                "detector_params": {"sr_breakout": {"touch_tolerance": 0.00000001}},
                "family_params": {"sr": {"touch_tolerance": 0.00000001}},
            }
        ],
        registry_meta={
            "sr_breakout": {
                "supported_regimes": ["RANGE"],
                "family": "sr",
                # No param_schema => params diagnosis must not run.
                "param_schema": {},
            }
        },
        window_stats=None,
    )

    row = details.get("sr_breakout") or {}
    causes = row.get("likely_causes") or []
    assert "PARAMS_INVALID" not in causes
    assert "PARAMS_TOO_STRICT" not in causes
