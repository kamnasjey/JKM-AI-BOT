from __future__ import annotations

from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


def test_public_payload_required_fields_and_stable_evidence_keys():
    from core.signal_payload_v1 import build_payload_v1
    from core.signal_payload_public_v1 import to_public_v1

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
    sig.signal_id = "fixed"
    sig.created_at = 123

    pub = to_public_v1(sig).model_dump(mode="json")

    # Required fields UI relies on.
    for k in [
        "schema_version",
        "signal_id",
        "ts_utc",
        "symbol",
        "timeframe",
        "status",
        "direction",
        "entry",
        "sl",
        "tp",
        "rr",
        "explain",
        "evidence",
        "chart_drawings",
    ]:
        assert k in pub

    assert pub["signal_id"] == "fixed"
    assert pub["ts_utc"] == 123
    assert pub["timeframe"] == "M15"

    # Stable evidence keys always present (values may be None).
    ev = pub["evidence"]
    assert isinstance(ev, dict)
    for k in ["entry", "sl", "tp", "rr", "entry_zone"]:
        assert k in ev


def test_drawings_have_type_alias_and_deterministic_order():
    from core.chart_annotation_builder import build_public_drawings_from_setup

    drawings = build_public_drawings_from_setup(1.0, 0.5, 2.0, entry_zone=None)
    dumped = [d.model_dump(mode="json") for d in drawings]

    # Deterministic base ordering from setup builder.
    object_ids = [d["object_id"] for d in dumped]
    assert object_ids == [
        "pubv1:line:entry",
        "pubv1:label:entry",
        "pubv1:line:sl",
        "pubv1:label:sl",
        "pubv1:line:tp",
        "pubv1:label:tp",
        "pubv1:box:risk",
        "pubv1:box:target",
    ]

    # `type` alias exists and matches `kind`.
    for d in dumped:
        assert d.get("type") in ("line", "label", "box")
        assert d.get("type") == d.get("kind")


def test_drawings_empty_when_all_na():
    from core.chart_annotation_builder import build_public_drawings_from_setup

    drawings = build_public_drawings_from_setup(None, None, None, entry_zone=None)
    assert drawings == []


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Patch side effects BEFORE importing the app module.
    import scanner_service as _scanner_mod
    import user_db as _user_db

    monkeypatch.setattr(_scanner_mod.scanner_service, "start", lambda: None, raising=False)
    monkeypatch.setattr(_scanner_mod.scanner_service, "stop", lambda: None, raising=False)
    monkeypatch.setattr(_user_db, "ensure_admin_account", lambda *_args, **_kwargs: None, raising=False)

    from apps.web_app import app as web_app

    # Patch auth.
    import apps.web_app as _web_mod

    monkeypatch.setattr(
        _web_mod,
        "_require_account",
        lambda _req: ({"user_id": "u1", "is_admin": True}, "token"),
        raising=True,
    )

    return TestClient(web_app)


def test_api_signal_detail_never_500_on_partial_payload(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    import apps.web_app as _web_mod

    # Simulate legacy payload missing many fields (must not crash / 500).
    monkeypatch.setattr(
        _web_mod,
        "get_signal_by_id_jsonl",
        lambda **_kwargs: {"signal_id": "x", "created_at": 1, "symbol": "XAUUSD", "tf": "M15"},
        raising=True,
    )

    r = client.get("/api/signals/x")
    assert r.status_code == 200
    body: Dict[str, Any] = r.json()
    assert body.get("signal_id") == "x"
    assert body.get("symbol") == "XAUUSD"
    assert body.get("timeframe") == "M15"
    assert isinstance(body.get("evidence"), dict)
    assert isinstance(body.get("chart_drawings"), list)
