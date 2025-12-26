from __future__ import annotations

import json


def test_invalid_enabled_strategy_is_reported_and_skipped(tmp_path):
    from strategies.loader import load_strategy_pack

    p = tmp_path / "strategies.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "include_presets": [],
                "strategies": [
                    {
                        "strategy_id": "bad1",
                        "enabled": True,
                        "max_top_hits": 0,
                        "min_score": 1.0,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE"],
                        "detectors": [],
                    },
                    {
                        "strategy_id": "good1",
                        "enabled": True,
                        "min_score": 1.0,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE"],
                        "detectors": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path / "presets"))
    assert len(pack.strategies) == 1
    assert pack.strategies[0].strategy_id == "good1"
    assert len(pack.invalid_enabled) == 1
    assert pack.invalid_enabled[0]["strategy_id"] == "bad1"
