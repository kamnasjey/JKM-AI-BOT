from __future__ import annotations

import os


def test_user_strategies_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_STRATEGIES_DIR", str(tmp_path))

    from core.user_strategies_store import load_user_strategies, save_user_strategies, user_strategies_path

    user_id = "u1"

    assert load_user_strategies(user_id) == []

    raw = [
        {
            "strategy_id": "range_reversal_v1",
            "enabled": True,
            "min_score": 1.0,
            "min_rr": 2.0,
            "allowed_regimes": ["RANGE", "CHOP"],
            "detectors": ["range_box_edge"],
        }
    ]

    res = save_user_strategies(user_id, raw)
    assert res["ok"] is True
    assert res["user_id"] == user_id
    assert isinstance(res["strategies"], list)
    assert res["strategies"], "expected at least one valid strategy"

    p = user_strategies_path(user_id)
    assert p.exists()

    loaded = load_user_strategies(user_id)
    assert isinstance(loaded, list)
    assert loaded and loaded[0].get("strategy_id") == "range_reversal_v1"


def test_user_strategies_store_invalid_returns_empty_and_warnings(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_STRATEGIES_DIR", str(tmp_path))

    from core.user_strategies_store import save_user_strategies

    # Unknown preset_id -> loader rejects with UNKNOWN_PRESET.
    raw = [{"preset_id": "__does_not_exist__"}]
    res = save_user_strategies("u1", raw)

    # Store always writes; the API layer decides whether to treat as 400.
    assert res["ok"] is True
    assert res["strategies"] == []
    assert res["warnings"], "expected validation warnings"
