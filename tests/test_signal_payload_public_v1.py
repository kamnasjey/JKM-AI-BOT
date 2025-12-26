from core.signal_payload_public_v1 import to_public_v1
from core.signal_payload_v1 import DrawingObjectV1, build_payload_v1


def test_public_conversion_basic_ok_and_evidence_keys():
    payload = build_payload_v1(
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
        explain={"rule": "demo"},
    )

    pub = to_public_v1(payload)
    assert pub.schema_name == "SignalPayloadPublicV1"
    assert pub.schema_version == 1
    assert pub.status == "OK"
    assert pub.direction == "BUY"

    dumped = pub.model_dump(mode="json")
    assert dumped.get("ts_utc") == pub.created_at
    assert dumped.get("timeframe") == pub.tf

    assert pub.evidence["entry"] == 2000.0
    assert pub.evidence["sl"] == 1990.0
    assert pub.evidence["tp"] == 2020.0
    assert pub.evidence["rr"] == 2.0
    assert "entry_zone" in pub.evidence

    # Drawings should include at least ENTRY/SL/TP lines.
    line_ids = [d.object_id for d in pub.chart_drawings if d.kind == "line"]
    assert set(["pubv1:line:entry", "pubv1:line:sl", "pubv1:line:tp"]).issubset(set(line_ids))


def test_public_conversion_na_safe_and_missing_evidence_does_not_crash():
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
        scan_id="scan1",
        explain={},
    )

    pub = to_public_v1(payload)
    assert pub.entry is None
    assert pub.sl is None
    assert pub.tp is None
    assert pub.rr is None

    # evidence must exist with stable keys
    assert set(["entry", "sl", "tp", "rr"]).issubset(set(pub.evidence.keys()))
    assert pub.evidence["entry"] is None

    # No values => no drawings.
    assert pub.chart_drawings == []


def test_public_conversion_skips_invalid_drawings():
    payload = build_payload_v1(
        user_id="u1",
        symbol="XAUUSD",
        tf="M15",
        direction="BUY",
        entry=2000.0,
        sl=None,
        tp=None,
        rr=None,
        strategy_id="s1",
        scan_id="scan1",
        explain={},
    )

    payload.drawings = [
        DrawingObjectV1(object_id="bad", kind="level", label="BAD", price=None),
        DrawingObjectV1(object_id="ok", kind="level", label="OK", price=2000.0),
    ]

    pub = to_public_v1(payload)
    ids = [d.object_id for d in pub.chart_drawings]
    assert "bad" not in ids
    assert "ok" in ids
    # Base drawings from setup should still exist.
    assert "pubv1:line:entry" in ids
