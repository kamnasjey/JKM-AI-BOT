from __future__ import annotations

import json

import pytest

from strategies.detector_name_resolver import resolve_detector_names
from strategies.loader import load_strategy_pack


def test_case_insensitive_match_resolves() -> None:
    res = resolve_detector_names(["SR_BOUNCE"], ["sr_bounce", "range_box_edge"])
    assert res.resolved == ["sr_bounce"]
    assert res.unknown == []


def test_fuzzy_suggestions_nonempty() -> None:
    res = resolve_detector_names(["sr_bounc"], ["sr_bounce", "range_box_edge"])
    assert res.resolved == []
    assert res.unknown == ["sr_bounc"]
    assert "sr_bounc" in res.suggestions
    assert any("sr_bounce" == x for x in res.suggestions["sr_bounc"])


def test_alias_applied_in_memory_only(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Create a pack file referencing an old detector name.
    pack_path = tmp_path / "strategies.json"
    pack_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "include_presets": [],
                "strategies": [
                    {
                        "strategy_id": "s1",
                        "enabled": True,
                        "min_score": 1.0,
                        "min_rr": 2.0,
                        "allowed_regimes": ["RANGE", "CHOP"],
                        "detectors": ["old_detector_name"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    # Alias file maps old name -> real detector.
    aliases_path = tmp_path / "detector_aliases.json"
    aliases_path.write_text(json.dumps({"old_detector_name": "sr_bounce"}), encoding="utf-8")
    monkeypatch.setenv("DETECTOR_ALIASES_PATH", str(aliases_path))

    pack = load_strategy_pack(str(pack_path), presets_dir=str(tmp_path))
    assert len(pack.strategies) == 1
    assert "sr_bounce" in pack.strategies[0].detectors

    # Warned, but did not rewrite file.
    assert any("DETECTOR_ALIAS_APPLIED" in w for w in (pack.warnings or []))
    raw = json.loads(pack_path.read_text(encoding="utf-8"))
    assert raw["strategies"][0]["detectors"] == ["old_detector_name"]
