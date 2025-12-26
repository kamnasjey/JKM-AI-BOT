import json

from core.signal_payload_public_v1 import SignalPayloadPublicV1, to_public_v1
from core.signal_payload_v1 import build_payload_v1


def test_public_v1_serialization_roundtrip():
    legacy = build_payload_v1(
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
    pub = to_public_v1(legacy)

    raw = pub.model_dump_json()
    data = json.loads(raw)
    assert data["schema_name"] == "SignalPayloadPublicV1"
    assert data["schema_version"] == 1
    assert data["ts_utc"] == data["created_at"]
    assert data["timeframe"] == data["tf"]

    parsed = SignalPayloadPublicV1.model_validate_json(raw)
    assert parsed.signal_id == pub.signal_id


def test_public_v1_drawings_present_when_values_exist():
    legacy = build_payload_v1(
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
    pub = to_public_v1(legacy)
    lines = [d for d in pub.chart_drawings if d.kind == "line"]
    assert len(lines) >= 3


def test_public_v1_drawings_empty_when_all_na():
    legacy = build_payload_v1(
        user_id="u1",
        symbol="XAUUSD",
        tf="M15",
        direction="NA",
        entry=None,
        sl=None,
        tp=None,
        rr=None,
        strategy_id="s1",
        scan_id="scan1",
        explain={},
    )
    pub = to_public_v1(legacy)
    assert pub.chart_drawings == []
