from __future__ import annotations

import json
import os

from scripts.apply_strategy_patch import apply_patch_workflow


def _write_strategies(path: str, *, min_score: float = 1.0) -> None:
    data = {
        "schema_version": 1,
        "include_presets": [],
        "strategies": [
            {
                "strategy_id": "range_reversal_v1",
                "enabled": True,
                "priority": 50,
                "min_score": float(min_score),
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": ["range_box_edge", "sr_bounce"],
                "conflict_epsilon": 0.05,
                "confluence_bonus_per_family": 0.25,
            }
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def test_patch_apply_dry_run_no_write(tmp_path) -> None:
    p = str(tmp_path / "strategies.json")
    _write_strategies(p, min_score=1.0)

    before = open(p, "r", encoding="utf-8").read()

    res = apply_patch_workflow(
        strategies_path=p,
        strategy_id="range_reversal_v1",
        changes={"min_score": {"from": 1.0, "to": 0.8}},
        dry_run=True,
    )
    assert res["ok"] is True
    assert res["backup_path"] is None

    after = open(p, "r", encoding="utf-8").read()
    assert after == before

    # No backup created
    assert not any(name.startswith("strategies.json.bak") for name in os.listdir(tmp_path))


def test_patch_apply_atomic_write_and_backup(tmp_path) -> None:
    p = str(tmp_path / "strategies.json")
    _write_strategies(p, min_score=1.0)
    before = open(p, "r", encoding="utf-8").read()

    res = apply_patch_workflow(
        strategies_path=p,
        strategy_id="range_reversal_v1",
        changes={"min_score": {"from": 1.0, "to": 0.8}},
        dry_run=False,
    )
    assert res["ok"] is True
    assert res["backup_path"]

    # Updated file
    after_obj = json.load(open(p, "r", encoding="utf-8"))
    assert after_obj["strategies"][0]["min_score"] == 0.8

    # Backup contains original
    bak = str(res["backup_path"])
    bak_obj = json.load(open(bak, "r", encoding="utf-8"))
    assert json.dumps(bak_obj, sort_keys=True) == json.dumps(json.loads(before), sort_keys=True)

    # Temp file not left behind
    assert not os.path.exists(p + ".tmp")


def test_patch_apply_validation_blocks_invalid(tmp_path) -> None:
    p = str(tmp_path / "strategies.json")
    _write_strategies(p, min_score=1.0)
    before = open(p, "r", encoding="utf-8").read()

    try:
        apply_patch_workflow(
            strategies_path=p,
            strategy_id="range_reversal_v1",
            changes={"min_score": {"from": 1.0, "to": -1.0}},
            dry_run=False,
        )
        assert False, "expected validation to fail"
    except Exception as e:
        assert "validation_failed" in str(e)

    # Original intact
    after = open(p, "r", encoding="utf-8").read()
    assert after == before

    # No backup created
    assert not any(name.startswith("strategies.json.bak") for name in os.listdir(tmp_path))
