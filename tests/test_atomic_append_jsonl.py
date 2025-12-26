import json

from core.signal_payload_v1 import build_payload_v1
from core.signals_store import append_signal_jsonl, list_signals_jsonl


def test_atomic_append_jsonl_valid_lines(tmp_path):
    path = tmp_path / "signals_v1.jsonl"

    for i in range(3):
        payload = build_payload_v1(
            user_id="u1",
            symbol="XAUUSD",
            tf="M15",
            direction="BUY",
            entry=None,
            sl=None,
            tp=None,
            rr=None,
            strategy_id=f"s{i}",
            scan_id=f"scan{i}",
        )
        append_signal_jsonl(payload, path=path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3

    for line in lines:
        obj = json.loads(line)
        assert isinstance(obj, dict)
        assert obj.get("signal_id")


def test_list_signals_jsonl_ignores_blank(tmp_path):
    path = tmp_path / "signals_v1.jsonl"
    path.write_text(
        "{\"signal_id\": \"a\", \"user_id\": \"u1\", \"symbol\": \"XAUUSD\"}\n\n"
        "{\"signal_id\": \"b\", \"user_id\": \"u1\", \"symbol\": \"XAUUSD\"}\n\n",
        encoding="utf-8",
    )

    out = list_signals_jsonl(user_id="u1", path=path, limit=10)
    assert [x.get("signal_id") for x in out] == ["b", "a"]
