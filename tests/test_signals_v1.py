from __future__ import annotations

import json
from pathlib import Path

from services.models import SignalEvent

from core.chart_annotation_builder import build_engine_annotations_v1_from_signal
from core.signal_payload_v1 import build_payload_v1
from core.signals_store import append_signal_jsonl, get_signal_by_id_jsonl, list_signals_jsonl


def test_engine_annotations_from_signal() -> None:
    sig = SignalEvent(
        pair="XAUUSD",
        direction="BUY",
        timeframe="M15",
        entry=2000.0,
        sl=1990.0,
        tp=2025.0,
        rr=2.5,
        reasons=["A", "B"],
    )

    ann = build_engine_annotations_v1_from_signal(sig)
    assert len(ann.levels) == 3
    assert ann.levels[0].price == 2000.0
    assert ann.levels[1].price == 1990.0
    assert ann.levels[2].price == 2025.0

    # Entry zone is optional (evidence-driven) and should be empty by default.
    assert ann.zones == []
    assert ann.fiboZones == []


def test_payload_serializes_and_roundtrips(tmp_path: Path) -> None:
    sig = SignalEvent(
        pair="EURUSD",
        direction="SELL",
        timeframe="M5",
        entry=1.1,
        sl=1.11,
        tp=1.08,
        rr=2.0,
        reasons=["TEST"],
    )
    ann = build_engine_annotations_v1_from_signal(sig)

    payload = build_payload_v1(
        user_id="1",
        symbol=sig.pair,
        tf=sig.timeframe,
        direction=sig.direction,
        entry=sig.entry,
        sl=sig.sl,
        tp=sig.tp,
        rr=sig.rr,
        strategy_id="strat",
        scan_id="scan",
        reasons=sig.reasons,
        explain={"status": "OK"},
        score=0.9,
        engine_annotations=ann,
    )

    path = tmp_path / "signals.jsonl"
    append_signal_jsonl(payload, path=path)

    items = list_signals_jsonl(user_id="1", limit=10, path=path)
    assert len(items) == 1
    assert items[0]["signal_id"] == payload.signal_id

    got = get_signal_by_id_jsonl(user_id="1", signal_id=payload.signal_id, path=path)
    assert got is not None
    assert got["symbol"] == "EURUSD"

    # Ensure JSON serializable
    json.dumps(got)


def test_user_scoping(tmp_path: Path) -> None:
    sig = SignalEvent(
        pair="XAUUSD",
        direction="BUY",
        timeframe="M15",
        entry=2000.0,
        sl=1990.0,
        tp=2025.0,
        rr=2.5,
        reasons=["A"],
    )
    ann = build_engine_annotations_v1_from_signal(sig)

    p1 = build_payload_v1(
        user_id="1",
        symbol=sig.pair,
        tf=sig.timeframe,
        direction=sig.direction,
        entry=sig.entry,
        sl=sig.sl,
        tp=sig.tp,
        rr=sig.rr,
        strategy_id="s",
        scan_id="x",
        reasons=sig.reasons,
        engine_annotations=ann,
    )
    p2 = build_payload_v1(
        user_id="2",
        symbol=sig.pair,
        tf=sig.timeframe,
        direction=sig.direction,
        entry=sig.entry,
        sl=sig.sl,
        tp=sig.tp,
        rr=sig.rr,
        strategy_id="s",
        scan_id="y",
        reasons=sig.reasons,
        engine_annotations=ann,
    )

    path = tmp_path / "signals.jsonl"
    append_signal_jsonl(p1, path=path)
    append_signal_jsonl(p2, path=path)

    items_u1 = list_signals_jsonl(user_id="1", limit=10, path=path)
    assert len(items_u1) == 1
    assert items_u1[0]["user_id"] == "1"

    # Other user should not fetch by id
    got = get_signal_by_id_jsonl(user_id="1", signal_id=p2.signal_id, path=path)
    assert got is None
