from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Patch side effects BEFORE importing the app module.
    import scanner_service as _scanner_mod
    import user_db as _user_db

    monkeypatch.setattr(_scanner_mod.scanner_service, "start", lambda: None, raising=False)
    monkeypatch.setattr(_scanner_mod.scanner_service, "stop", lambda: None, raising=False)
    monkeypatch.setattr(_user_db, "ensure_admin_account", lambda *_args, **_kwargs: None, raising=False)

    # Ensure user strategies are stored under tmp.
    monkeypatch.setenv("USER_STRATEGIES_DIR", str(tmp_path))

    from apps.web_app import app as web_app

    # Patch auth.
    import apps.web_app as _web_mod

    monkeypatch.setattr(
        _web_mod,
        "_require_account",
        lambda _req: ({"user_id": "u1", "is_admin": False}, "token"),
        raising=True,
    )

    return TestClient(web_app)


def test_user_strategies_put_then_get(client: TestClient):
    payload: Dict[str, Any] = {
        "strategies": [
            {
                "strategy_id": "range_reversal_v1",
                "enabled": True,
                "min_score": 1.0,
                "min_rr": 2.0,
                "allowed_regimes": ["RANGE", "CHOP"],
                "detectors": ["range_box_edge"],
            }
        ]
    }

    r1 = client.put("/api/strategies", json=payload)
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["ok"] is True
    assert body1["user_id"] == "u1"
    assert body1["strategies"] and body1["strategies"][0]["strategy_id"] == "range_reversal_v1"

    r2 = client.get("/api/strategies")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["user_id"] == "u1"
    assert body2["strategies"] and body2["strategies"][0]["strategy_id"] == "range_reversal_v1"


def test_user_strategies_invalid_returns_400(client: TestClient):
    r = client.put("/api/strategies", json={"strategies": [{"preset_id": "__does_not_exist__"}]})
    assert r.status_code == 400
