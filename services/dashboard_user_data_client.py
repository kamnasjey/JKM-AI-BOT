from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass(frozen=True)
class DashboardUserDataClient:
    """Client for interacting with dashboard internal user-data API.
    
    This is the canonical interface for user data when provider=dashboard/firebase.
    All user data (prefs, strategies, signals, identity) flows through the dashboard.
    """
    
    base_url: str
    api_key: str
    timeout_s: float = 4.0

    @staticmethod
    def from_env() -> Optional["DashboardUserDataClient"]:
        """Create client from environment variables.
        
        Required env vars:
        - DASHBOARD_USER_DATA_URL or DASHBOARD_BASE_URL
        - DASHBOARD_INTERNAL_API_KEY
        """
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

    # =========================================================================
    # STRATEGIES
    # =========================================================================

    def get_strategies(self, user_id: str) -> List[Dict[str, Any]]:
        """Get user strategies from Firestore via dashboard."""
        url = f"{self.base_url}/api/internal/user-data/strategies/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.get(url, headers=self._headers())
        res.raise_for_status()
        data = res.json()
        strategies = data.get("strategies")
        return list(strategies) if isinstance(strategies, list) else []

    def put_strategies(self, user_id: str, strategies: List[Dict[str, Any]]) -> None:
        """Save user strategies to Firestore via dashboard."""
        url = f"{self.base_url}/api/internal/user-data/strategies/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.put(url, headers=self._headers(), json={"strategies": strategies})
        res.raise_for_status()

    # =========================================================================
    # SIGNALS
    # =========================================================================

    def upsert_signal(self, *, user_id: str, signal_key: str, signal: Dict[str, Any]) -> None:
        """Upsert a signal to Firestore via dashboard."""
        url = f"{self.base_url}/api/internal/user-data/signals"
        payload = {"user_id": str(user_id), "signal_key": str(signal_key), "signal": signal}
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.post(url, headers=self._headers(), json=payload)
        res.raise_for_status()

    def list_signals(
        self,
        user_id: str,
        limit: int = 50,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List signals for a user from Firestore via dashboard.
        
        Args:
            user_id: User ID to list signals for
            limit: Max signals to return (default 50, max 500)
            symbol: Optional symbol filter
            status: Optional status filter (pending, hit_tp, hit_sl, expired)
            
        Returns:
            List of signal dicts
        """
        url = f"{self.base_url}/api/internal/user-data/signals"
        params: Dict[str, Any] = {"user_id": user_id, "limit": limit}
        if symbol:
            params["symbol"] = symbol
        if status:
            params["status"] = status
            
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.get(url, headers=self._headers(), params=params)
        res.raise_for_status()
        data = res.json()
        signals = data.get("signals")
        return list(signals) if isinstance(signals, list) else []

    # =========================================================================
    # USERS / IDENTITY / PREFS
    # =========================================================================

    def list_active_users(self, source: str = "prisma") -> List[Dict[str, Any]]:
        """List paid users for scanning.
        
        Args:
            source: "prisma" (default) or "firestore"
            
        Returns:
            List of user dicts with identity + prefs
        """
        url = f"{self.base_url}/api/internal/user-data/users"
        params = {"source": source}
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.get(url, headers=self._headers(), params=params)
        res.raise_for_status()
        data = res.json()
        users = data.get("users")
        return list(users) if isinstance(users, list) else []

    def get_user_prefs(self, user_id: str) -> Dict[str, Any]:
        """Get user prefs from Firestore via dashboard.
        
        Returns combined identity + prefs dict.
        """
        url = f"{self.base_url}/api/internal/user-data/users/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.get(url, headers=self._headers())
        res.raise_for_status()
        data = res.json()
        prefs = data.get("prefs")
        return dict(prefs) if isinstance(prefs, dict) else {}

    def put_user_prefs(self, user_id: str, prefs: Dict[str, Any]) -> None:
        """Update user prefs in Firestore via dashboard.
        
        Accepts telegram_chat_id, telegram_enabled, scan_enabled, plan, plan_status.
        """
        url = f"{self.base_url}/api/internal/user-data/users/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.put(url, headers=self._headers(), json={"prefs": prefs})
        res.raise_for_status()

    def put_user_identity(self, user_id: str, identity: Dict[str, Any]) -> None:
        """Update user identity in Firestore via dashboard.
        
        Accepts email, name, has_paid_access, plan, plan_status.
        Used for syncing from legacy local DB to Firestore.
        """
        url = f"{self.base_url}/api/internal/user-data/users/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.put(url, headers=self._headers(), json={"identity": identity})
        res.raise_for_status()

    def put_user_full(self, user_id: str, identity: Dict[str, Any], prefs: Dict[str, Any]) -> None:
        """Update both identity and prefs in Firestore via dashboard.
        
        Convenience method for migration.
        """
        url = f"{self.base_url}/api/internal/user-data/users/{user_id}"
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.put(url, headers=self._headers(), json={
                "identity": identity,
                "prefs": prefs,
            })
        res.raise_for_status()

    # =========================================================================
    # HEALTH
    # =========================================================================

    def health_check(self, skip_prisma: bool = False) -> Dict[str, Any]:
        """Check dashboard user-data API health.
        
        Returns:
            Dict with ok, checks (firestore, prisma), ms
        """
        url = f"{self.base_url}/api/internal/user-data/health"
        params = {"skip_prisma": "true"} if skip_prisma else {}
        with httpx.Client(timeout=self.timeout_s) as client:
            res = client.get(url, headers=self._headers(), params=params)
        res.raise_for_status()
        return res.json()
