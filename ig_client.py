# ig_client.py
"""
IG Markets REST API client – login хийж, candles татах.

ENV хувьсагчууд:
  IG_API_KEY
  IG_USERNAME
  IG_PASSWORD
  IG_ACCOUNT_ID
  IG_IS_DEMO = "true" / "false"

EPIC хувьсагчууд (pair бүрийн):
  EPIC_XAUUSD
  EPIC_EURJPY
  EPIC_GBPJPY
  ...

Эдгээрийг Render / .env дээрээ тохируулна.
"""

from __future__ import annotations
import os
from typing import List, Dict, Any, Optional

import requests


class IGClient:
    DEMO_BASE = "https://demo-api.ig.com/gateway/deal"
    LIVE_BASE = "https://api.ig.com/gateway/deal"

    def __init__(
        self,
        api_key: str,
        username: str,
        password: str,
        account_id: str,
        is_demo: bool = False,
    ) -> None:
        self.api_key = api_key
        self.username = username
        self.password = password
        self.account_id = account_id
        self.base_url = self.DEMO_BASE if is_demo else self.LIVE_BASE

        self.session = requests.Session()
        self.cst: Optional[str] = None
        self.x_security_token: Optional[str] = None
        self._authenticated = False

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls, is_demo: bool = False) -> "IGClient":
        api_key = os.getenv("IG_API_KEY", "")
        username = os.getenv("IG_USERNAME", "")
        password = os.getenv("IG_PASSWORD", "")
        account_id = os.getenv("IG_ACCOUNT_ID", "")

        if not api_key or not username or not password or not account_id:
            raise RuntimeError("IG ENV тохиргоо дутуу байна (IG_API_KEY, IG_USERNAME, IG_PASSWORD, IG_ACCOUNT_ID).")

        client = cls(api_key, username, password, account_id, is_demo=is_demo)
        client.login()
        return client

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def login(self) -> None:
        url = f"{self.base_url}/session"
        headers = {
            "X-IG-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Version": "2",
        }
        data = {
            "identifier": self.username,
            "password": self.password,
        }
        resp = self.session.post(url, json=data, headers=headers)
        resp.raise_for_status()

        self.cst = resp.headers.get("CST")
        self.x_security_token = resp.headers.get("X-SECURITY-TOKEN")
        self._authenticated = True

        # Account switch
        acc_url = f"{self.base_url}/session"
        acc_headers = {
            "X-IG-API-KEY": self.api_key,
            "CST": self.cst,
            "X-SECURITY-TOKEN": self.x_security_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Version": "1",
        }
        acc_data = {"accountId": self.account_id, "defaultAccount": True}
        self.session.put(acc_url, json=acc_data, headers=acc_headers)

    def _auth_headers(self, version: str = "3") -> Dict[str, str]:
        if not self._authenticated:
            self.login()
        return {
            "X-IG-API-KEY": self.api_key,
            "CST": self.cst or "",
            "X-SECURITY-TOKEN": self.x_security_token or "",
            "Accept": "application/json",
            "Version": version,
        }

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------
    def get_candles(
        self,
        epic: str,
        resolution: str,
        max_points: int = 300,
    ) -> List[Dict[str, Any]]:
        """
        /prices/{epic}/{resolution}/{max} endpoint-оор свеч татах.
        Буцаах формат: [{time, open, high, low, close}, ...]
        """
        url = f"{self.base_url}/prices/{epic}/{resolution}/{max_points}"
        headers = self._auth_headers(version="3")

        resp = self.session.get(url, headers=headers)
        resp.raise_for_status()

        data = resp.json()
        prices = data.get("prices", [])

        candles: List[Dict[str, Any]] = []

        for p in prices:
            t = p.get("snapshotTimeUTC") or p.get("snapshotTime")
            op = p.get("openPrice", {})
            hp = p.get("highPrice", {})
            lp = p.get("lowPrice", {})
            cp = p.get("closePrice", {})

            # bid/ask-аас дундаж авах (simple)
            def _mid(x: Dict[str, Any]) -> float:
                b = float(x.get("bid", 0.0))
                a = float(x.get("ask", 0.0))
                if b == 0 and a == 0:
                    return float(x.get("lastTraded", 0.0))
                return (b + a) / 2.0 if a and b else (b or a)

            candles.append(
                {
                    "time": t,
                    "open": _mid(op),
                    "high": _mid(hp),
                    "low": _mid(lp),
                    "close": _mid(cp),
                }
            )

        return candles
