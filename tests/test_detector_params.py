from __future__ import annotations

import json


def test_params_merge_order_family_then_detector():
    from engine.utils.params_utils import merge_param_layers

    merged = merge_param_layers(
        base={"a": 1, "x": "base"},
        family={"x": "family", "b": 2},
        detector={"x": "detector", "c": 3},
    )
    assert merged["a"] == 1
    assert merged["b"] == 2
    assert merged["c"] == 3
    assert merged["x"] == "detector"


def test_unknown_detector_params_warns(tmp_path):
    from strategies.loader import load_strategy_pack

    p = tmp_path / "strategies.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "strategies": [
                    {
                        "strategy_id": "s1",
                        "enabled": True,
                        "min_score": 1.0,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE"],
                        "detectors": ["range_box_edge"],
                        "detector_params": {
                            "range_box_edge": {"box_lookback": 120},
                            "unknown_x": {"a": 1}
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path / "presets"))
    assert len(pack.strategies) == 1
    assert any(w.startswith("UNKNOWN_DETECTOR_PARAMS:unknown_x") for w in pack.warnings)


def test_invalid_params_type_ignored_not_crash(tmp_path):
    from strategies.loader import load_strategy_pack

    p = tmp_path / "strategies.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "strategies": [
                    {
                        "strategy_id": "s1",
                        "enabled": True,
                        "min_score": 1.0,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE"],
                        "detectors": ["range_box_edge"],
                        "detector_params": {
                            "range_box_edge": 123
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path / "presets"))
    assert len(pack.strategies) == 1
    s = pack.strategies[0]
    assert getattr(s, "detector_params", {}) == {}
    assert any(w.startswith("DETECTOR_PARAMS_IGNORED_NOT_OBJECT:range_box_edge") for w in pack.warnings)
