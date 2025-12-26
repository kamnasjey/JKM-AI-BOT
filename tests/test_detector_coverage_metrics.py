from __future__ import annotations

from metrics.daily_summary import summarize_events


def test_coverage_counts_from_events(monkeypatch) -> None:
    # Avoid depending on real registry; return empty loaded detectors list.
    import metrics.daily_summary as ds

    monkeypatch.setattr(ds, "_loaded_detector_names", lambda: [])

    events = [
        {"status": "OK", "strategy_id": "S1", "reason": "OK", "regime": "RANGE", "top_hits": ["a", "b"]},
        # NONE events may carry top_hits but are excluded from coverage counts.
        {"status": "NONE", "strategy_id": "S1", "reason": "NO_HITS", "regime": "RANGE", "top_hits": ["b"]},
        {"status": "OK", "strategy_id": "S2", "reason": "OK", "regime": "CHOP", "top_hits": ["a"]},
        # Backward-compatible: missing top_hits should not crash.
        {"status": "OK", "strategy_id": "S2", "reason": "OK", "regime": "CHOP"},
    ]

    summary = summarize_events(events, date="2099-01-01", window_hours=24)

    assert summary.ok_count == 3
    assert summary.detector_hit_counts.get("a") == 2
    # 'b' appears in NONE event but should not be counted.
    assert summary.detector_hit_counts.get("b") == 1

    # hit rates are relative to ok_count
    assert abs(summary.detector_hit_rates.get("a", 0.0) - (2.0 / 3.0)) < 1e-9
    assert abs(summary.detector_hit_rates.get("b", 0.0) - (1.0 / 3.0)) < 1e-9

    # per-strategy counts are OK-only
    s1 = summary.per_strategy_top_detectors.get("S1")
    assert isinstance(s1, list) and s1
    assert any((isinstance(it, dict) and it.get("detector") == "b") for it in s1)


def test_dead_detectors_detected(monkeypatch) -> None:
    import metrics.daily_summary as ds

    monkeypatch.setattr(ds, "_loaded_detector_names", lambda: ["a", "b", "dead"])

    events = [
        {"status": "OK", "strategy_id": "S1", "reason": "OK", "regime": "RANGE", "top_hits": ["a", "b"]},
        {"status": "NONE", "strategy_id": "S1", "reason": "NO_HITS", "regime": "RANGE", "top_hits": ["b"]},
    ]

    summary = summarize_events(events, date="2099-01-01", window_hours=24)
    assert "dead" in summary.dead_detectors
    assert "a" not in summary.dead_detectors
    assert "b" not in summary.dead_detectors


def test_per_strategy_top_detectors_counts(monkeypatch) -> None:
    import metrics.daily_summary as ds

    monkeypatch.setattr(ds, "_loaded_detector_names", lambda: [])

    events = [
        {"status": "OK", "strategy_id": "A", "reason": "OK", "regime": "RANGE", "top_hits": ["x", "y", "x"]},
        {"status": "OK", "strategy_id": "A", "reason": "OK", "regime": "RANGE", "top_hits": ["y"]},
        {"status": "OK", "strategy_id": "B", "reason": "OK", "regime": "RANGE", "top_hits": ["x"]},
        {"status": "NONE", "strategy_id": "A", "reason": "NO_HITS", "regime": "RANGE", "top_hits": ["z"]},
    ]

    summary = summarize_events(events, date="2099-01-01", window_hours=24)

    # Strategy A: x=2, y=2 (NONE ignored)
    a = summary.per_strategy_top_detectors.get("A")
    assert a is not None
    a_map = {it["detector"]: it["count"] for it in a if isinstance(it, dict)}
    assert a_map.get("x") == 2
    assert a_map.get("y") == 2

    compact = summary.per_strategy_top_detectors_compact
    assert compact.get("A") is not None
    assert any(s.startswith("x:") for s in compact.get("A") or [])


def test_limits_applied(monkeypatch) -> None:
    import metrics.daily_summary as ds

    monkeypatch.setattr(ds, "_loaded_detector_names", lambda: [])

    # Create 5 strategies, each with 5 detectors.
    events = []
    for i in range(5):
        sid = f"S{i}"
        hits = [f"d{j}" for j in range(5)]
        events.append({"status": "OK", "strategy_id": sid, "reason": "OK", "regime": "RANGE", "top_hits": hits})

    summary = summarize_events(events, date="2099-01-01", window_hours=24)
    compact = summary.per_strategy_top_detectors_compact

    assert isinstance(compact, dict)
    assert len(compact) <= 3
    for _, vals in compact.items():
        assert isinstance(vals, list)
        assert len(vals) <= 3
