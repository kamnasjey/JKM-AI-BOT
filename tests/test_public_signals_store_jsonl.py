from core.signal_payload_public_v1 import to_public_v1
from core.signal_payload_v1 import build_payload_v1
from core.signals_store import (
    append_public_signal_jsonl,
    get_public_signal_by_id_jsonl,
    list_public_signals_jsonl,
)


def test_public_jsonl_list_get_missing_file_ok(tmp_path):
    path = tmp_path / "signals.jsonl"
    assert list_public_signals_jsonl(user_id="u1", path=path) == []
    assert get_public_signal_by_id_jsonl(user_id="u1", signal_id="nope", path=path) is None


def test_public_jsonl_list_get_empty_file_ok(tmp_path):
    path = tmp_path / "signals.jsonl"
    path.write_text("", encoding="utf-8")
    assert list_public_signals_jsonl(user_id="u1", path=path) == []
    assert get_public_signal_by_id_jsonl(user_id="u1", signal_id="nope", path=path) is None


def test_public_jsonl_append_then_list_get_ok(tmp_path):
    path = tmp_path / "signals.jsonl"

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

    append_public_signal_jsonl(pub, path=path)

    items = list_public_signals_jsonl(user_id="u1", path=path, limit=10)
    assert len(items) == 1
    assert items[0].get("schema_name") == "SignalPayloadPublicV1"
    assert items[0].get("signal_id") == legacy.signal_id

    got = get_public_signal_by_id_jsonl(user_id="u1", signal_id=legacy.signal_id, path=path)
    assert got is not None
    assert got.get("signal_id") == legacy.signal_id
