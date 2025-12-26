from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient


def _fake_candles() -> List[Dict[str, Any]]:
    # Deterministic candle shape (as cache returns).
    return [
        {"time": 1, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
        {"time": 2, "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0},
        {"time": 3, "open": 2.0, "high": 3.0, "low": 1.5, "close": 2.5},
    ]


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Patch side effects BEFORE importing the app module.
    import scanner_service as _scanner_mod
    import user_db as _user_db

    monkeypatch.setattr(_scanner_mod.scanner_service, "start", lambda: None, raising=False)
    monkeypatch.setattr(_scanner_mod.scanner_service, "stop", lambda: None, raising=False)
    monkeypatch.setattr(_user_db, "ensure_admin_account", lambda *_args, **_kwargs: None, raising=False)

    # Import after patching.
    from apps.web_app import app as web_app

    # Patch candle cache.
    import market_data_cache as _mdc

    monkeypatch.setattr(_mdc.market_cache, "get_candles", lambda _sym: _fake_candles(), raising=False)

    # Patch auth for signal endpoints.
    import apps.web_app as _web_mod

    monkeypatch.setattr(
        _web_mod,
        "_require_account",
        lambda _req: ({"user_id": "u1", "is_admin": True}, "token"),
        raising=True,
    )

    # Patch signal lookup to deterministic payload.
    from core.signal_payload_v1 import build_payload_v1

    sig = build_payload_v1(
        user_id="u1",
        symbol="XAUUSD",
        tf="M15",
        direction="BUY",
        entry=2000.0,
        sl=1990.0,
        tp=2020.0,
        rr=2.0,
        strategy_id="s1",
        scan_id="scan1",
        explain={},
    )
    # Make stable IDs/timestamps for test equality.
    sig.signal_id = "fixed-signal-id"
    sig.created_at = 123

    monkeypatch.setattr(
        _web_mod,
        "get_signal_by_id_jsonl",
        lambda **_kwargs: sig.model_dump(mode="json"),
        raising=True,
    )

    return TestClient(web_app)


def test_api_candles_missing_symbol_returns_422_or_400(client: TestClient):
    r = client.get("/api/candles")
    assert r.status_code in (400, 422)


def test_api_candles_and_markets_candles_identical(client: TestClient):
    r1 = client.get("/api/candles", params={"symbol": "EURUSD", "tf": "5m", "limit": 2})
    r2 = client.get("/api/markets/EURUSD/candles", params={"tf": "5m", "limit": 2})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_api_signal_alias_matches_plural_detail(client: TestClient):
    r1 = client.get("/api/signals/fixed-signal-id")
    r2 = client.get("/api/signal/fixed-signal-id")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()
