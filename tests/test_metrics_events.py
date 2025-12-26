from __future__ import annotations

import json

from metrics.scan_metrics import MetricsEvent, emit_event


def test_emit_event_jsonl_appends(tmp_path) -> None:
    p = tmp_path / "events.jsonl"

    e1 = MetricsEvent(
        ts=1.0,
        scan_id="s1",
        symbol="EURUSD",
        tf="M15",
        strategy_id="st1",
        status="OK",
        reason="OK",
        score=0.5,
        score_raw=0.5,
        bonus=0.0,
        rr=2.0,
        regime="RANGE",
        candidates=None,
        failover_used=None,
        params_digest="d1",
    )
    e2 = MetricsEvent(
        ts=2.0,
        scan_id="s2",
        symbol="XAUUSD",
        tf="M15",
        strategy_id="st2",
        status="NONE",
        reason="NO_HITS",
        score=None,
        score_raw=None,
        bonus=None,
        rr=None,
        regime="RANGE",
        candidates=[{"strategy_id": "st2"}],
        failover_used=False,
        params_digest="NA",
    )

    emit_event(e1, path=str(p))
    emit_event(e2, path=str(p))

    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    obj1 = json.loads(lines[0])
    obj2 = json.loads(lines[1])
    assert obj1["symbol"] == "EURUSD"
    assert obj2["status"] == "NONE"
