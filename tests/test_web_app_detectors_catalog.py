from __future__ import annotations

from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Patch side effects BEFORE importing the app module.
    import scanner_service as _scanner_mod
    import user_db as _user_db

    monkeypatch.setattr(_scanner_mod.scanner_service, "start", lambda: None, raising=False)
    monkeypatch.setattr(_scanner_mod.scanner_service, "stop", lambda: None, raising=False)
    monkeypatch.setattr(_user_db, "ensure_admin_account", lambda *_args, **_kwargs: None, raising=False)

    from apps.web_app import app as web_app

    import apps.web_app as _web_mod

    monkeypatch.setattr(
        _web_mod,
        "_require_account",
        lambda _req: ({"user_id": "u1", "is_admin": True}, "token"),
        raising=True,
    )

    # Patch registry to a deterministic set where one detector has no docs.
    from detectors.base import BaseDetector, DetectorSignal

    class DocDet(BaseDetector):
        name = "a_doc"
        doc = "Has docs"
        params_schema = {"params.x": {"type": "int", "default": 1}}
        examples = [{"config": {"enabled": True, "params": {"x": 1}}}]

        def detect(self, *args: Any, **kwargs: Any) -> Optional[DetectorSignal]:
            return None

    class NoDocDet(BaseDetector):
        name = "b_nodoc"

        def detect(self, *args: Any, **kwargs: Any) -> Optional[DetectorSignal]:
            return None

    import detectors.registry as _reg

    monkeypatch.setattr(_reg, "DETECTOR_REGISTRY", {"a_doc": DocDet, "b_nodoc": NoDocDet}, raising=True)

    return TestClient(web_app)


def test_detectors_default_names_only(client: TestClient):
    r = client.get("/api/detectors")
    assert r.status_code == 200
    body = r.json()
    assert body == {"detectors": ["a_doc", "b_nodoc"]}


def test_detectors_include_docs_na_safe_defaults(client: TestClient):
    r = client.get("/api/detectors", params={"include_docs": 1})
    assert r.status_code == 200
    body: Dict[str, Any] = r.json()

    assert "detectors" in body
    dets = body["detectors"]
    assert isinstance(dets, list)
    assert [d.get("name") for d in dets] == ["a_doc", "b_nodoc"]

    for d in dets:
        assert set(["name", "doc", "params_schema", "examples"]).issubset(set(d.keys()))
        assert isinstance(d.get("doc"), str)
        assert isinstance(d.get("params_schema"), dict)
        assert isinstance(d.get("examples"), list)
