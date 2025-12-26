from __future__ import annotations

import json
import logging

import pytest

from engine.utils.logging_utils import log_kv
from strategies.loader import load_strategy_pack, summarize_unknown_detectors


def _write_pack(path, strategies) -> None:
    obj = {
        "schema_version": 1,
        "include_presets": [],
        "strategies": strategies,
    }
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_unknown_detector_names_listed_in_logs(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
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
                "detectors": ["range_box_edge", "UNKNOWN_DET_A"],
            },
            {
                "strategy_id": "s2",
                "enabled": True,
                "min_score": 1.0,
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": ["sr_bounce", "UNKNOWN_DET_B"],
            },
        ],
    )

    caplog.set_level(logging.INFO)
    logger = logging.getLogger("t_unknown_det_logs")

    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path))
    summary = summarize_unknown_detectors(pack, max_items=10)

    log_kv(
        logger,
        "STRATEGIES_LOADED",
        path=str(p),
        count=len(pack.strategies),
        **summary,
    )

    text = "\n".join([r.message for r in caplog.records])
    assert "UNKNOWN_DET_A" in text
    assert "UNKNOWN_DET_B" in text
    assert "s1" in text
    assert "s2" in text


def test_strict_mode_disables_strategy(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRICT_STRATEGY_DETECTORS", "1")

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
                "detectors": ["range_box_edge", "UNKNOWN_DET_X"],
            }
        ],
    )

    pack = load_strategy_pack(str(p), presets_dir=str(tmp_path))

    # Strategy is disabled in-memory (not loaded)
    assert all(s.strategy_id != "s1" for s in pack.strategies)

    disabled = getattr(pack, "disabled_unknown_detectors", {})
    assert "s1" in disabled
    assert "UNKNOWN_DET_X" in (disabled.get("s1") or [])

    # Unknown mapping preserved for observability
    unknown = getattr(pack, "unknown_detectors_by_strategy", {})
    assert "s1" in unknown
    assert "UNKNOWN_DET_X" in (unknown.get("s1") or [])
