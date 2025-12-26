from __future__ import annotations

import json
import os

import pytest

from scripts.apply_strategy_patch import apply_patch_and_audit
from scripts.rollback_strategy_patch import rollback_patch


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


def test_apply_writes_patch_audit_line(tmp_path) -> None:
    strategies_path = str(tmp_path / "strategies.json")
    audit_path = str(tmp_path / "patch_audit.jsonl")
    _write_strategies(strategies_path, min_score=1.0)

    res = apply_patch_and_audit(
        strategies_path=strategies_path,
        strategy_id="range_reversal_v1",
        changes={"min_score": {"from": 1.0, "to": 0.8}},
        dry_run=False,
        audit_path=audit_path,
        patch_type="TEST",
        strategy_ids=["range_reversal_v1"],
    )
    assert res["ok"] is True
    assert os.path.exists(audit_path)

    lines = [x for x in open(audit_path, "r", encoding="utf-8").read().splitlines() if x.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["patch_id"] == res["patch_id"]
    assert obj["backup_path"]
    assert obj["file_path"] == strategies_path
    assert obj["dry_run"] is False
    assert obj["before"].get("min_score") == 1.0
    assert obj["after"].get("min_score") == 0.8


def test_rollback_restores_backup_content(tmp_path) -> None:
    strategies_path = str(tmp_path / "strategies.json")
    audit_path = str(tmp_path / "patch_audit.jsonl")
    _write_strategies(strategies_path, min_score=1.0)

    before = open(strategies_path, "r", encoding="utf-8").read()

    res = apply_patch_and_audit(
        strategies_path=strategies_path,
        strategy_id="range_reversal_v1",
        changes={"min_score": {"from": 1.0, "to": 0.8}},
        dry_run=False,
        audit_path=audit_path,
        patch_type="TEST",
        strategy_ids=["range_reversal_v1"],
    )

    # File changed
    assert "\"min_score\": 0.8" in open(strategies_path, "r", encoding="utf-8").read()

    # Rollback
    rb = rollback_patch(
        patch_id=str(res["patch_id"]),
        audit_path=audit_path,
        strategies_path=strategies_path,
        dry_run=False,
        validate=True,
    )
    assert rb["ok"] is True

    after = open(strategies_path, "r", encoding="utf-8").read()
    assert after == before


def test_rollback_missing_backup_safe_fail(tmp_path) -> None:
    strategies_path = str(tmp_path / "strategies.json")
    audit_path = str(tmp_path / "patch_audit.jsonl")
    _write_strategies(strategies_path, min_score=1.0)

    original = open(strategies_path, "r", encoding="utf-8").read()

    # Write audit referencing missing backup.
    entry = {
        "ts": 123,
        "patch_id": "deadbeef",
        "patch_type": "TEST",
        "strategy_ids": ["range_reversal_v1"],
        "file_path": strategies_path,
        "backup_path": str(tmp_path / "missing.bak"),
        "dry_run": False,
        "before": {"min_score": 1.0},
        "after": {"min_score": 0.8},
    }
    with open(audit_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    with pytest.raises(FileNotFoundError):
        rollback_patch(
            patch_id="deadbeef",
            audit_path=audit_path,
            strategies_path=strategies_path,
            dry_run=False,
            validate=False,
        )

    # No overwrite
    assert open(strategies_path, "r", encoding="utf-8").read() == original
