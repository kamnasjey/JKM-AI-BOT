from __future__ import annotations

import json

import pytest

from scripts.apply_strategy_patch import apply_patch_workflow
from strategies.loader import load_strategy_pack, summarize_unknown_detectors


def _write_pack(path, strategies) -> None:
    obj = {
        "schema_version": 1,
        "include_presets": [],
        "strategies": strategies,
    }
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_autopatch_generated_for_high_confidence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure patch registry writes in tmp.
    monkeypatch.chdir(tmp_path)

    p = tmp_path / "strategies.json"
    _write_pack(
        p,
        [
            {
                "strategy_id": "s1",
                "enabled": True,
                "min_score": 1.0,
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": ["sr_bounc"],
            }
        ],
    )

    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path))
    patches = getattr(pack, "unknown_detector_autofix_patches", [])
    assert isinstance(patches, list)
    assert len(patches) == 1
    it = patches[0]
    assert it.get("patch_type") == "FIX_UNKNOWN_DETECTORS"
    assert it.get("strategy_id") == "s1"
    assert it.get("replacements") == {"sr_bounc": "sr_bounce"}

    # Apply patch and reload => unknown detectors should be 0.
    apply_patch_workflow(
        strategies_path=str(p),
        strategy_id="s1",
        changes=it.get("changes") or {},
        dry_run=False,
    )
    pack2 = load_strategy_pack(str(p), presets_dir=str(tmp_path))
    summary = summarize_unknown_detectors(pack2)
    assert summary.get("unknown_detectors_count") == 0


def test_autopatch_not_generated_for_low_confidence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    p = tmp_path / "strategies.json"
    _write_pack(
        p,
        [
            {
                "strategy_id": "s1",
                "enabled": True,
                "min_score": 1.0,
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": ["completely_wrong_detector_name"],
            }
        ],
    )

    monkeypatch.setenv("UNKNOWN_DETECTOR_AUTOFIX_THRESHOLD", "0.95")
    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path))
    patches = getattr(pack, "unknown_detector_autofix_patches", [])
    assert isinstance(patches, list)
    assert len(patches) == 0


def test_patch_preview_detectors_replaced_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    p = tmp_path / "strategies.json"
    _write_pack(
        p,
        [
            {
                "strategy_id": "s1",
                "enabled": True,
                "min_score": 1.0,
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": ["sr_bounc", "range_box_edge"],
            }
        ],
    )

    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path))
    patches = getattr(pack, "unknown_detector_autofix_patches", [])
    assert len(patches) == 1
    preview = str(patches[0].get("dry_run_preview") or "")
    assert preview.startswith("detectors:")
    assert "min_score" not in preview
    assert "allowed_regimes" not in preview
    assert "sr_bounce" in preview
