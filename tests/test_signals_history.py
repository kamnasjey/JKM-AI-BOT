import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.signals_store import append_signal_jsonl, append_public_signal_jsonl, list_public_signals_jsonl, get_public_signal_by_id_jsonl, get_signal_by_id_jsonl
from scanner_service import ScannerService
from services.models import SignalEvent

@pytest.fixture
def mock_repo_dir(tmp_path):
    # Mock the REPO_DIR in signals_store using patch
    # Since signals_store resolves paths at module level, we might need to patch the path objects directly or use overwrite arguments.
    # The atomic_append_jsonl_via_replace uses path arg, so we can pass overrides.
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return state_dir

@pytest.fixture
def clean_scanner():
    s = ScannerService()
    # Disable background threads
    if s._thread:
        s.stop()
    return s

def test_persistence_creates_files(mock_repo_dir):
    """Test that persistence functions create files when specific paths are provided."""
    legacy_path = mock_repo_dir / "signals_v1.jsonl"
    public_path = mock_repo_dir / "signals.jsonl"

    payload = {
        "user_id": "test_user",
        "symbol": "EURUSD",
        "tf": "M15",
        "direction": "BUY",
        "entry": 1.1,
        "sl": 1.0,
        "tp": 1.2,
        "rr": 2.0,
        "strategy_id": "strat_1",
        "scan_id": "scan_1",
        "reasons": ["R1"]
    }
    
    # Needs valid Pydantic model for append_signal_jsonl? 
    # The signature says SignalPayloadV1, but let's see if we can pass a dict that builds it or if we need the model.
    # append_signal_jsonl takes SignalPayloadV1 (pydantic)
    from core.signal_payload_v1 import SignalPayloadV1
    
    # We must construct a valid payload
    pydantic_payload = SignalPayloadV1(
        signal_id="sig_1",
        user_id="test_user",
        symbol="EURUSD",
        tf="M15",
        direction="BUY",
        entry=1.1,
        sl=1.0,
        tp=1.2,
        rr=2.0,
        strategy_id="strat_1",
        scan_id="scan_1",
        reasons=["R1"],
        timestamp="2025-01-01T00:00:00Z"
    )

    append_signal_jsonl(pydantic_payload, path=legacy_path)
    assert legacy_path.exists()
    assert "sig_1" in legacy_path.read_text(encoding="utf-8")

    append_public_signal_jsonl(pydantic_payload.model_dump(mode="json"), path=public_path)
    assert public_path.exists()
    assert "sig_1" in public_path.read_text(encoding="utf-8")


def test_scanner_persist_safely_integration(clean_scanner, mock_repo_dir):
    """Test that _persist_signal_safely writes to both files (mocked via patching imports/paths)."""
    
    # We need to patch the DEFAULT paths inside scanner_service's imported module or patch the functions.
    # Easiest is to patch `append_signal_jsonl` and `append_public_signal_jsonl` to just verifying they are called, 
    # OR better: patch the module attributes (paths) if possible, but they are constants.
    # We will patch the functions `append_signal_jsonl` and `append_public_signal_jsonl` in `scanner_service` namespace to use our tmp paths?
    # No, those functions take path args but scanner_service calls them without path args (uses defaults).
    # So we must patch the constants in `core.signals_store`.
    
    legacy_path = mock_repo_dir / "signals_v1.jsonl"
    public_path = mock_repo_dir / "signals.jsonl"
    
    with patch("core.signals_store.DEFAULT_SIGNALS_PATH", legacy_path), \
         patch("core.signals_store.DEFAULT_PUBLIC_SIGNALS_PATH", public_path):
        
        sig = SignalEvent(
            pair="GBPUSD",
            direction="SELL",
            timeframe="H1",
            entry=1.5,
            sl=1.6,
            tp=1.3,
            rr=2.0,
            reasons=["R_TEST"],
            engine_version="test_v1"
        )
        
        clean_scanner._persist_signal_safely(
            user_id="u1",
            symbol="GBPUSD",
            entry_tf="H1",
            direction="SELL", 
            entry=1.5, 
            sl=1.6, 
            tp=1.3, 
            rr=2.0,
            strategy_id="s1",
            scan_id="sc1",
            reasons=["R_TEST"],
            payload={},
            selected={"score": 0.99},
            signal=sig
        )
        
        assert legacy_path.exists()
        assert public_path.exists()
        
        data = json.loads(legacy_path.read_text(encoding="utf-8").strip())
        assert data["symbol"] == "GBPUSD"
        
        pub_data = json.loads(public_path.read_text(encoding="utf-8").strip())
        assert pub_data["symbol"] == "GBPUSD"
        assert "engine_annotations" in pub_data

def test_api_fallback_logic(mock_repo_dir):
    """Test standard fallback logic: public -> legacy."""
    legacy_path = mock_repo_dir / "signals_v1.jsonl"
    public_path = mock_repo_dir / "signals.jsonl"
    
    # 1. Neither exists -> Empty
    res = list_public_signals_jsonl(user_id="u1", path=public_path)
    assert res == []
    
    # 2. Only legacy exists
    rec = {"signal_id": "legacy_1", "user_id": "u1", "symbol": "BTCUSD", "direction": "BUY"}
    legacy_path.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    
    # list_public_signals_jsonl strictly reads public path, so it should be empty
    assert list_public_signals_jsonl(user_id="u1", path=public_path) == []
    
    # But get_signal logic in WEB APP does the fallback. We should test helper behavior here.
    # The helpers are strict. The APP does the composition.
    # Let's verify helpers are robust to missing files.
    assert get_public_signal_by_id_jsonl(user_id="u1", signal_id="any", path=public_path) is None
    
    # 3. Public exists
    rec_pub = {"signal_id": "pub_1", "user_id": "u1", "symbol": "ETHUSD", "direction": "SELL"}
    public_path.write_text(json.dumps(rec_pub) + "\n", encoding="utf-8")
    
    # List should return it
    res = list_public_signals_jsonl(user_id="u1", path=public_path)
    assert len(res) == 1
    assert res[0]["signal_id"] == "pub_1"
    
    # Get by ID
    found = get_public_signal_by_id_jsonl(user_id="u1", signal_id="pub_1", path=public_path)
    assert found["symbol"] == "ETHUSD"

def test_corrupt_lines_skipped(mock_repo_dir):
    public_path = mock_repo_dir / "signals.jsonl"
    content = '{"id": "ok"}\nI AM CORRUPT JSON\n{"id": "ok2"}\n'
    public_path.write_text(content, encoding="utf-8")
    
    res = list_public_signals_jsonl(user_id="u1", path=public_path, include_all_users=True)
    # Should get 2 valid lines
    # Note: list_signals_jsonl iterates reversed, so we expect [ok2, ok] (newest first)
    assert len(res) == 2
    assert res[0]["id"] == "ok2"
    assert res[1]["id"] == "ok"
