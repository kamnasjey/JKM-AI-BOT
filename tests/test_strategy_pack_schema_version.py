from __future__ import annotations

import json


def test_strategy_pack_missing_schema_version_warns(tmp_path):
    from strategies.loader import load_strategy_pack

    p = tmp_path / "strategies.json"
    p.write_text(
        json.dumps(
            {
                # intentionally no schema_version
                "strategies": [
                    {
                        "strategy_id": "s1",
                        "enabled": True,
                        "min_score": 1.0,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE"],
                        "detectors": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path / "presets"))
    assert pack.schema_version == 1
    assert "SCHEMA_VERSION_MISSING_DEFAULT_1" in pack.warnings
    assert len(pack.strategies) == 1
