from __future__ import annotations

import json


def test_strategy_pack_include_presets_user_override_wins(tmp_path):
    from strategies.loader import load_strategy_pack

    presets_dir = tmp_path / "presets"
    presets_dir.mkdir(parents=True, exist_ok=True)

    # Preset pack defines two strategies
    (presets_dir / "pack1.json").write_text(
        json.dumps(
            {
                "preset_id": "pack1",
                "schema_version": 1,
                "strategies": [
                    {
                        "strategy_id": "s_range",
                        "enabled": True,
                        "min_score": 0.9,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE"],
                        "detectors": [],
                    },
                    {
                        "strategy_id": "s_trend",
                        "enabled": True,
                        "min_score": 1.1,
                        "min_rr": 3.0,
                        "allowed_regimes": ["TREND_BULL"],
                        "detectors": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    # User overrides s_range
    strategies_path = tmp_path / "strategies.json"
    strategies_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "include_presets": ["pack1"],
                "strategies": [
                    {
                        "strategy_id": "s_range",
                        "enabled": True,
                        "min_score": 2.5,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE"],
                        "detectors": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    pack = load_strategy_pack(str(strategies_path), presets_dir=str(presets_dir))
    assert pack.loaded_presets == ["pack1"]

    by_id = {s.strategy_id: s for s in pack.strategies}
    assert set(by_id.keys()) == {"s_range", "s_trend"}
    assert by_id["s_range"].min_score == 2.5
