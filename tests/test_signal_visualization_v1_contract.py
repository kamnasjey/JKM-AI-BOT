from __future__ import annotations

import json
from pathlib import Path

from services.models import SignalEvent

from core.chart_annotation_builder import build_engine_annotations_v1_from_signal
from core.signal_payload_v1 import SignalPayloadV1, build_payload_v1
from core.signals_store import append_signal_jsonl, get_signal_by_id_jsonl


def test_schema_serialization_roundtrip() -> None:
    payload = build_payload_v1(
        user_id="u1",
        symbol="EURUSD",
        tf="M15",
        direction="BUY",
        entry=1.1,
        sl=1.09,
        tp=1.12,
        rr=2.0,
        strategy_id="s1",
        scan_id="scan_1",
        reasons=["R1"],
        explain={"schema_version": 1, "status": "OK"},
        score=0.75,
    )

    # Pydantic model -> dict -> json must work
    dumped = payload.model_dump(mode="json")
    assert dumped.get("schema_version") == 1
    json.dumps(dumped)

    # Dict -> model must work
    SignalPayloadV1(**dumped)


def test_na_safety_missing_values_does_not_crash() -> None:
    payload = build_payload_v1(
        user_id="u1",
        symbol="XAUUSD",
        tf="M15",
        direction="SELL",
        entry=None,
        sl=None,
        tp=None,
        rr=None,
        strategy_id="s1",
        scan_id="scan_2",
        reasons=None,
        explain=None,
        score=None,
    )

    assert payload.entry is None
    assert payload.sl is None
    assert payload.tp is None
    assert payload.rr is None
    assert payload.drawings == []


def test_drawings_present_when_entry_sl_tp_exist() -> None:
    payload = build_payload_v1(
        user_id="u1",
        symbol="EURUSD",
        tf="M15",
        direction="BUY",
        entry=1.1,
        sl=1.09,
        tp=1.12,
        rr=2.0,
        strategy_id="s1",
        scan_id="scan_3",
        reasons=["OK"],
        explain={"schema_version": 1, "status": "OK"},
        score=0.9,
    )

    kinds = [d.kind for d in payload.drawings]
    assert kinds.count("level") == 3
    labels = [str(d.label or "") for d in payload.drawings]
    assert any("ENTRY" in x for x in labels)
    assert any(x == "SL" for x in labels)
    assert any(x.startswith("TP") for x in labels)


def test_drawings_empty_when_all_na() -> None:
    payload = build_payload_v1(
        user_id="u1",
        symbol="EURUSD",
        tf="M15",
        direction="BUY",
        entry="NA",
        sl=None,
        tp=float("nan"),
        rr=None,
        strategy_id="s1",
        scan_id="scan_4",
    )

    assert payload.drawings == []


def test_optional_entry_zone_box_from_evidence() -> None:
    # Evidence contains entry_zone bounds -> should produce a zone drawing.
    payload = build_payload_v1(
        user_id="u1",
        symbol="EURUSD",
        tf="M15",
        direction="BUY",
        entry=1.1,
        sl=1.09,
        tp=1.12,
        rr=2.0,
        strategy_id="s1",
        scan_id="scan_5",
        explain={"schema_version": 1, "status": "OK", "evidence": {"entry_zone": {"price_from": 1.095, "price_to": 1.105}}},
    )

    assert any(d.kind == "zone" for d in payload.drawings)


def test_persist_jsonl_atomic_and_signal_id_exists(tmp_path: Path) -> None:
    payload = build_payload_v1(
        user_id="u1",
        symbol="EURUSD",
        tf="M15",
        direction="BUY",
        entry=1.1,
        sl=1.09,
        tp=1.12,
        rr=2.0,
        strategy_id="s1",
        scan_id="scan_6",
    )

    path = tmp_path / "signals.jsonl"
    append_signal_jsonl(payload, path=path)

    raw = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(raw) == 1
    obj = json.loads(raw[0])
    assert obj.get("signal_id")

    got = get_signal_by_id_jsonl(user_id="u1", signal_id=str(obj["signal_id"]), path=path)
    assert got is not None


def test_annotation_builder_is_na_safe() -> None:
    sig = SignalEvent(
        pair="EURUSD",
        direction="BUY",
        timeframe="M15",
        entry=None,
        sl=None,
        tp=None,
        rr=None,
        reasons=[],
    )

    ann = build_engine_annotations_v1_from_signal(sig)
    assert ann.levels == []
    assert ann.zones == []
