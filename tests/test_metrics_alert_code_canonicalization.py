from __future__ import annotations

import json

from metrics.alert_codes import (
    TOP_REASON_DOMINANCE,
    canonicalize_alert_code,
)
from state.metrics_alert_state import load_alert_state, save_alert_state_atomic


def test_alias_mapping_canonicalizes() -> None:
    assert canonicalize_alert_code("ok_rate_below_min") == "OK_RATE_LOW"
    assert canonicalize_alert_code("OK_RATE_MIN") == "OK_RATE_LOW"
    assert canonicalize_alert_code("NO_HITS_DOMINANT") == TOP_REASON_DOMINANCE
    assert canonicalize_alert_code("no_hits_dominance") == TOP_REASON_DOMINANCE


def test_state_migration_legacy_code(tmp_path) -> None:
    state_path = str(tmp_path / "metrics_alert_state.json")

    legacy = {
        "schema": 1,
        "alerts": {
            "OK_RATE_BELOW_MIN": {"active": True, "last_triggered_date": "2099-01-01"},
            "NO_HITS_DOMINANT": {"active": True, "last_triggered_date": "2099-01-01"},
        },
    }
    save_alert_state_atomic(legacy, state_path)

    st = load_alert_state(state_path)
    assert st["schema"] == 1
    assert "OK_RATE_LOW" in st["alerts"]
    assert TOP_REASON_DOMINANCE in st["alerts"]

    # Ensure legacy keys are not present after load.
    assert "OK_RATE_BELOW_MIN" not in st["alerts"]
    assert "NO_HITS_DOMINANT" not in st["alerts"]

    # Still valid JSON on disk.
    raw = (tmp_path / "metrics_alert_state.json").read_text(encoding="utf-8")
    json.loads(raw)
