from __future__ import annotations

import pytest

from metrics.alert_codes import OK_RATE_LOW
from metrics.recommendations import generate_recommendations


def test_patch_generator_never_suggests_unknown_detector(monkeypatch: pytest.MonkeyPatch) -> None:
    # Restrict known detectors to a single name.
    from engines import detectors as det_mod

    monkeypatch.setattr(det_mod.detector_registry, "list_detectors", lambda: ["sr_bounce"])

    strategies_json = {
        "schema_version": 1,
        "include_presets": [],
        "strategies": [
            {
                "strategy_id": "range_reversal_v1",
                "enabled": True,
                "priority": 50,
                "min_score": 1.0,
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": [],
                "conflict_epsilon": 0.05,
                "confluence_bonus_per_family": 0.25,
            }
        ],
    }

    summary = {
        "date": "2025-12-23",
        "total_pairs": 100,
        "ok_count": 1,
        "top_reasons": [{"reason": "NO_HITS", "count": 80}],
        "top_strategies_by_ok": [{"strategy_id": "range_reversal_v1", "ok_count": 1}],
    }

    recos = generate_recommendations(summary, alert_codes={OK_RATE_LOW}, strategies_json=strategies_json)

    # If a detector is suggested, it must be from the known registry (sr_bounce).
    for r in recos:
        for a in (r.actions or []):
            if a.type != "edit_strategy":
                continue
            det_change = (a.changes or {}).get("detectors")
            if not det_change:
                continue
            to_list = det_change.get("to")
            assert isinstance(to_list, list)
            assert all(d == "sr_bounce" for d in to_list)
