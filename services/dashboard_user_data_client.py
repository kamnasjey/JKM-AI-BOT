from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass(frozen=True)
class DashboardUserDataClient:
    base_url: str
    api_key: str
    timeout_s: float = 4.0

    @staticmethod
    def from_env() -> Optional["DashboardUserDataClient"]:
        base = (os.getenv("DASHBOARD_USER_DATA_URL") or os.getenv("DASHBOARD_BASE_URL") or "").strip()
        key = (os.getenv("DASHBOARD_INTERNAL_API_KEY") or "").strip()
        if not base or not key:
            return None
        return DashboardUserDataClient(base_url=base.rstrip("/"), api_key=key)

    def _headers(self) -> Dict[str, str]:
        return {
            "x-internal-api-key": self.api_key,
            "content-type": "application/json",
            "accept": "application/json",
        }

    def get_strategies(self, user_id: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/internal/user-data/strategies/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.get(url, headers=self._headers())
        res.raise_for_status()
        data = res.json()
        strategies = data.get("strategies")
        return list(strategies) if isinstance(strategies, list) else []

    def put_strategies(self, user_id: str, strategies: List[Dict[str, Any]]) -> None:
        url = f"{self.base_url}/api/internal/user-data/strategies/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.put(url, headers=self._headers(), json={"strategies": strategies})
        res.raise_for_status()

    def upsert_signal(self, *, user_id: str, signal_key: str, signal: Dict[str, Any]) -> None:
        url = f"{self.base_url}/api/internal/user-data/signals"
        payload = {"user_id": str(user_id), "signal_key": str(signal_key), "signal": signal}
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.post(url, headers=self._headers(), json=payload)
        res.raise_for_status()

    def list_active_users(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/internal/user-data/users"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.get(url, headers=self._headers())
        res.raise_for_status()
        data = res.json()
        users = data.get("users")
        return list(users) if isinstance(users, list) else []

    def get_user_prefs(self, user_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/internal/user-data/users/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.get(url, headers=self._headers())
        res.raise_for_status()
        data = res.json()
        prefs = data.get("prefs")
        return dict(prefs) if isinstance(prefs, dict) else {}

    def put_user_prefs(self, user_id: str, prefs: Dict[str, Any]) -> None:
        url = f"{self.base_url}/api/internal/user-data/users/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.put(url, headers=self._headers(), json={"prefs": prefs})
        res.raise_for_status()
