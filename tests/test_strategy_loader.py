"""tests.test_strategy_loader

Step 6: Strategy loader tests.

Validates:
- load_strategies() reads config shape
- unknown detector names are dropped (but strategy stays enabled)

Run:
    pytest -q
"""

from __future__ import annotations

import json


def test_load_strategies_drops_unknown_detector(tmp_path):
    from strategies.loader import load_strategies

    p = tmp_path / "strategies.json"
    p.write_text(
        json.dumps(
            {
                "strategies": [
                    {
                        "strategy_id": "range_reversal_v1",
                        "enabled": True,
                        "min_score": 1.0,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE", "CHOP"],
                        "detectors": ["range_box_edge", "UNKNOWN_DETECTOR_X"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    specs = load_strategies(str(p))
    assert len(specs) == 1
    assert specs[0].strategy_id == "range_reversal_v1"
    assert "range_box_edge" in specs[0].detectors
    assert "UNKNOWN_DETECTOR_X" not in specs[0].detectors
