from __future__ import annotations

import json
import time

from metrics.daily_summary import read_events_jsonl, summarize_events


def test_daily_summary_aggregates_correctly(tmp_path) -> None:
    p = tmp_path / "events.jsonl"
    now = time.time()

    events = [
        {
            "ts": now - 10,
            "scan_id": "s",
            "symbol": "EURUSD",
            "tf": "M15",
            "strategy_id": "A",
            "status": "OK",
            "reason": "OK",
            "score": 0.6,
            "rr": 2.0,
            "regime": "RANGE",
        },
        {
            "ts": now - 9,
            "scan_id": "s",
            "symbol": "EURUSD",
            "tf": "M15",
            "strategy_id": "A",
            "status": "NONE",
            "reason": "NO_HITS",
            "score": None,
            "rr": None,
            "regime": "RANGE",
        },
        {
            "ts": now - 8,
            "scan_id": "s",
            "symbol": "XAUUSD",
            "tf": "M15",
            "strategy_id": "B",
            "status": "NONE",
            "reason": "COOLDOWN_ACTIVE",
            "regime": "CHOP",
        },
    ]

    p.write_text("\n".join([json.dumps(e) for e in events]) + "\n", encoding="utf-8")
    loaded = read_events_jsonl(str(p), since_ts=now - 3600)
    summary = summarize_events(loaded, date="2099-01-01", window_hours=24)

    assert summary.total_pairs == 3
    assert summary.ok_count == 1
    assert abs(summary.ok_rate - (1.0 / 3.0)) < 1e-9
    assert summary.cooldown_blocks == 1
    assert summary.daily_limit_blocks == 0
    assert summary.avg_score is not None and abs(summary.avg_score - 0.6) < 1e-9
    assert summary.avg_rr is not None and abs(summary.avg_rr - 2.0) < 1e-9


def test_na_fields_handled(tmp_path) -> None:
    p = tmp_path / "events.jsonl"
    now = time.time()

    events = [
        {
            "ts": now - 10,
            "scan_id": "s",
            "symbol": "EURUSD",
            "tf": "M15",
            "strategy_id": "A",
            "status": "OK",
            "reason": "OK",
            "score": "NA",
            "rr": "NA",
            "regime": "RANGE",
        }
    ]

    p.write_text("\n".join([json.dumps(e) for e in events]) + "\n", encoding="utf-8")
    loaded = read_events_jsonl(str(p), since_ts=now - 3600)
    summary = summarize_events(loaded, date="2099-01-01", window_hours=24)

    assert summary.total_pairs == 1
    assert summary.ok_count == 1
    assert summary.avg_score is None
    assert summary.avg_rr is None
