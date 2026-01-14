"""
test_privacy_mode.py

Tests for privacy mode enforcement:
1. When PRIVACY_MODE=1 and provider=dashboard, no local files should be created
2. When PRIVACY_MODE=1, purge_local_user_artifacts should clean up existing files
3. Dashboard client should be used for all user data operations
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator
from unittest import mock

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test artifacts."""
    import shutil
    d = Path(tempfile.mkdtemp(prefix="jkm_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_privacy_env() -> Generator[None, None, None]:
    """Set privacy mode environment variables."""
    env_patch = {
        "JKM_PRIVACY_MODE": "1",
        "PRIVACY_MODE": "1",
        "USER_STRATEGIES_PROVIDER": "dashboard",
        "USER_SIGNALS_PROVIDER": "dashboard",
        "USER_DB_PROVIDER": "dashboard",
        "USER_ACCOUNTS_PROVIDER": "dashboard",
        "USER_TELEGRAM_PROVIDER": "dashboard",
        "DASHBOARD_BASE_URL": "https://test.example.com",
        "DASHBOARD_INTERNAL_API_KEY": "test-key",
    }
    with mock.patch.dict(os.environ, env_patch):
        yield


class TestPrivacyMode:
    """Tests for privacy mode functions."""
    
    def test_privacy_mode_enabled_with_env(self):
        """Test privacy_mode_enabled returns True when env is set."""
        from core.privacy import privacy_mode_enabled
        
        with mock.patch.dict(os.environ, {"JKM_PRIVACY_MODE": "1"}):
            assert privacy_mode_enabled() is True
        
        with mock.patch.dict(os.environ, {"PRIVACY_MODE": "true"}):
            assert privacy_mode_enabled() is True
        
        with mock.patch.dict(os.environ, {"JKM_PRIVACY_MODE": "yes"}):
            assert privacy_mode_enabled() is True
    
    def test_privacy_mode_disabled_by_default(self):
        """Test privacy_mode_enabled returns False when env is not set."""
        from core.privacy import privacy_mode_enabled
        
        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove privacy mode vars if they exist
            env_copy = os.environ.copy()
            env_copy.pop("JKM_PRIVACY_MODE", None)
            env_copy.pop("PRIVACY_MODE", None)
            with mock.patch.dict(os.environ, env_copy, clear=True):
                assert privacy_mode_enabled() is False
    
    def test_should_use_dashboard_for_users(self, mock_privacy_env):
        """Test should_use_dashboard_for_users returns True in privacy mode."""
        from core.privacy import should_use_dashboard_for_users
        
        assert should_use_dashboard_for_users() is True
    
    def test_purge_local_user_artifacts(self, temp_dir: Path):
        """Test purge_local_user_artifacts deletes expected files."""
        from core.privacy import purge_local_user_artifacts
        
        # Create test files
        (temp_dir / "user_profiles.db").write_text("test db")
        (temp_dir / "user_profiles.json").write_text("{}")
        state_dir = temp_dir / "state"
        state_dir.mkdir()
        (state_dir / "plugin_events.jsonl").write_text("test events")
        (state_dir / "events_queue.db").write_text("test queue")
        
        # Create user strategies dir
        strategies_dir = state_dir / "user_strategies"
        strategies_dir.mkdir()
        (strategies_dir / "user1.json").write_text('{"strategies": []}')
        (strategies_dir / "user2.json").write_text('{"strategies": []}')
        
        # Verify files exist
        assert (temp_dir / "user_profiles.db").exists()
        assert (strategies_dir / "user1.json").exists()
        
        # Purge
        count = purge_local_user_artifacts(base_dir=temp_dir, verbose=False)
        
        # Verify files deleted
        assert not (temp_dir / "user_profiles.db").exists()
        assert not (temp_dir / "user_profiles.json").exists()
        assert not (state_dir / "plugin_events.jsonl").exists()
        assert not (strategies_dir / "user1.json").exists()
        assert not (strategies_dir / "user2.json").exists()
        
        # Should have deleted 6 files total
        assert count == 6


class TestUserStrategiesStorePrivacy:
    """Tests for user_strategies_store in privacy mode."""
    
    def test_load_user_strategies_uses_dashboard(self, mock_privacy_env):
        """Test load_user_strategies calls dashboard client in privacy mode."""
        from core.user_strategies_store import load_user_strategies
        
        mock_strategies = [
            {"strategy_id": "strat1", "name": "Test", "enabled": True, "detectors": ["swing_low"]}
        ]
        
        mock_client = mock.MagicMock()
        mock_client.get_strategies.return_value = mock_strategies
        
        with mock.patch(
            "core.user_strategies_store.DashboardUserDataClient.from_env",
            return_value=mock_client
        ):
            result = load_user_strategies("test-user")
        
        mock_client.get_strategies.assert_called_once_with("test-user")
        assert len(result) == 1
        assert result[0]["strategy_id"] == "strat1"
    
    def test_save_user_strategies_uses_dashboard(self, mock_privacy_env):
        """Test save_user_strategies calls dashboard client in privacy mode."""
        from core.user_strategies_store import save_user_strategies
        
        mock_client = mock.MagicMock()
        mock_client.put_strategies.return_value = None
        
        test_strategies = [
            {"strategy_id": "strat1", "name": "Test", "enabled": True, "detectors": ["swing_low"]}
        ]
        
        with mock.patch(
            "core.user_strategies_store.DashboardUserDataClient.from_env",
            return_value=mock_client
        ):
            result = save_user_strategies("test-user", test_strategies)
        
        assert result["ok"] is True
        assert result["storage_provider"] == "dashboard"
        mock_client.put_strategies.assert_called_once()
    
    def test_save_fails_without_dashboard_in_privacy_mode(self):
        """Test save_user_strategies fails gracefully without dashboard config."""
        from core.user_strategies_store import save_user_strategies
        
        env_patch = {
            "JKM_PRIVACY_MODE": "1",
            "USER_STRATEGIES_PROVIDER": "dashboard",
            # No DASHBOARD_BASE_URL or DASHBOARD_INTERNAL_API_KEY
        }
        
        with mock.patch.dict(os.environ, env_patch, clear=True):
            with mock.patch(
                "core.user_strategies_store.DashboardUserDataClient.from_env",
                return_value=None
            ):
                result = save_user_strategies("test-user", [])
        
        assert result["ok"] is False
        assert "missing" in result["error"].lower() or "dashboard" in result["error"].lower()


class TestSignalsTrackerPrivacy:
    """Tests for signals_tracker in privacy mode."""
    
    def test_record_signal_uses_dashboard(self, mock_privacy_env):
        """Test record_signal calls dashboard client when provider is dashboard."""
        from signals_tracker import record_signal
        from services.models import SignalEvent
        
        mock_client = mock.MagicMock()
        mock_client.upsert_signal.return_value = None
        
        signal = SignalEvent(
            pair="BTCUSDT",
            direction="long",
            timeframe="1h",
            entry=50000.0,
            sl=48000.0,
            tp=55000.0,
            rr=2.5,
        )
        
        with mock.patch(
            "signals_tracker.DashboardUserDataClient.from_env",
            return_value=mock_client
        ):
            result = record_signal(user_id="test-user", signal=signal, strategy_name="Test")
        
        # Should return None (no local ID) and call dashboard
        assert result is None
        mock_client.upsert_signal.assert_called_once()
        
        # Verify the call args
        call_kwargs = mock_client.upsert_signal.call_args.kwargs
        assert call_kwargs["user_id"] == "test-user"
        assert "signal_key" in call_kwargs
        assert call_kwargs["signal"]["symbol"] == "BTCUSDT"


class TestDashboardUserDataClient:
    """Tests for the DashboardUserDataClient."""
    
    def test_from_env_returns_none_without_config(self):
        """Test from_env returns None when env vars are missing."""
        from services.dashboard_user_data_client import DashboardUserDataClient
        
        with mock.patch.dict(os.environ, {}, clear=True):
            client = DashboardUserDataClient.from_env()
            assert client is None
    
    def test_from_env_returns_client_with_config(self):
        """Test from_env returns client when env vars are set."""
        from services.dashboard_user_data_client import DashboardUserDataClient
        
        with mock.patch.dict(os.environ, {
            "DASHBOARD_BASE_URL": "https://test.example.com",
            "DASHBOARD_INTERNAL_API_KEY": "test-key",
        }):
            client = DashboardUserDataClient.from_env()
            assert client is not None
            assert client.base_url == "https://test.example.com"
            assert client.api_key == "test-key"
    
    def test_list_signals_builds_correct_url(self):
        """Test list_signals constructs correct request."""
        from services.dashboard_user_data_client import DashboardUserDataClient
        
        client = DashboardUserDataClient(
            base_url="https://test.example.com",
            api_key="test-key",
        )
        
        # Mock httpx.Client
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {"ok": True, "signals": []}
        mock_response.raise_for_status.return_value = None
        
        mock_client = mock.MagicMock()
        mock_client.__enter__ = mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = mock.MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        
        with mock.patch("httpx.Client", return_value=mock_client):
            result = client.list_signals("test-user", limit=100, symbol="BTCUSDT")
        
        # Verify the request
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args[0][0] == "https://test.example.com/api/internal/user-data/signals"
        assert call_args[1]["params"]["user_id"] == "test-user"
        assert call_args[1]["params"]["limit"] == 100
        assert call_args[1]["params"]["symbol"] == "BTCUSDT"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
