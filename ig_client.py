# ig_client.py
"""
IG Markets REST API client – login хийж, candles татах.

ENV хувьсагчууд:
  IG_API_KEY
  IG_USERNAME
  IG_PASSWORD
  IG_ACCOUNT_ID
  IG_IS_DEMO = "true" / "false"  # demo=True бол demo-api, false бол live-api

EPIC хувьсагчууд (pair бүрийн):
  EPIC_XAUUSD
  EPIC_EURJPY
  EPIC_GBPJPY
  ...

Эдгээрийг локал болон серверийн ENV дээрээ тохируулна.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests


class IGClient:
    """IG REST API-д холбогдох энгийн client."""

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
        self.is_demo = is_demo

        self.base_url = self.DEMO_BASE if is_demo else self.LIVE_BASE

        self.session = requests.Session()
        self.cst: Optional[str] = None
        self.x_security_token: Optional[str] = None
        self._authenticated: bool = False

    # ------------------------------------------------------------------
    # Env-ээс client үүсгэх
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls, is_demo: Optional[bool] = None) -> "IGClient":
        """
        ENV хувьсагчиас IGClient үүсгэнэ.

        - is_demo нь None байвал IG_IS_DEMO env-ээс уншина.
        - is_demo=True/False өгвөл ENV-ээс үл хамааран тэр утгыг хэрэглэнэ.
        """
        api_key = os.getenv("IG_API_KEY", "")
        username = os.getenv("IG_USERNAME", "")
        password = os.getenv("IG_PASSWORD", "")
        account_id = os.getenv("IG_ACCOUNT_ID", "")

        if is_demo is None:
            is_demo_raw = os.getenv("IG_IS_DEMO", "false").strip().lower()
            # "true", "1", "yes" бол demo, бусад нь live-api гэж үзнэ
            is_demo_val = is_demo_raw in ("true", "1", "yes", "y")
        else:
            is_demo_val = is_demo

        if not api_key or not username or not password or not account_id:
            raise RuntimeError(
                "IG ENV тохиргоо дутуу байна (IG_API_KEY, IG_USERNAME, "
                "IG_PASSWORD, IG_ACCOUNT_ID заавал хэрэгтэй)."
            )

        client = cls(api_key, username, password, account_id, is_demo=is_demo_val)
        client.login()
        return client

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def login(self) -> None:
        """IG API-д нэвтэрч CST + X-SECURITY-TOKEN авах."""
        url = f"{self.base_url}/session"
        print(
            f"[IGClient] Trying login: base_url={self.base_url}, "
            f"account_id={self.account_id}, is_demo={self.is_demo}"
        )

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

        if resp.status_code >= 400:
            # login алдааг дэлгэрэнгүй хэвлэнэ
            print("\n====== IG LOGIN ERROR ======")
            print("URL:", url)
            print("Status code:", resp.status_code)
            print("Response headers:", resp.headers)
            try:
                print("Response JSON:", resp.json())
            except Exception:
                print("Response text:", resp.text)
            print("====== END IG LOGIN ERROR ======\n")
            resp.raise_for_status()

        # Амжилттай бол CST, token-уудыг хадгална
        self.cst = resp.headers.get("CST")
        self.x_security_token = resp.headers.get("X-SECURITY-TOKEN")
        self._authenticated = True

        # Нэвтэрсний дараа account сонгоно
        self._switch_account()

    def _switch_account(self) -> None:
        """
        Өгөгдсөн account_id руу шилжинэ.

        Хэрэв 412 (Precondition Failed) гарах юм бол:
        - ихэвчлэн accountId зөрсөн эсвэл энэ үйлдэл шаардлагагүй үед гардаг
        - одоохондоо default account-оор үргэлжлүүлээд, зөвхөн анхааруулга хэвлэнэ.
        """
        if not self.account_id:
            # account_id өгөгдөөгүй бол юу ч хийхгүй
            return

        url = f"{self.base_url}/session"
        headers = {
            "X-IG-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Version": "1",
            "CST": self.cst or "",
            "X-SECURITY-TOKEN": self.x_security_token or "",
        }
        data = {
            "accountId": self.account_id,
            "defaultAccount": True,
        }

        resp = self.session.put(url, json=data, headers=headers)

        if resp.status_code == 412:
            # Энд алдааны мессежийг логонд харуулна
            print("\n====== IG ACCOUNT SWITCH WARNING ======")
            print("Tried to switch accountId:", self.account_id)
            try:
                print("Response JSON:", resp.json())
            except Exception:
                print("Response text:", resp.text)
            print("412 Precondition Failed -> continuing with default account.")
            print("====== END IG ACCOUNT SWITCH WARNING ======\n")
            # default account-аар үргэлжлүүлнэ, exception шидэхгүй
            return

        # 412 биш өөр алдаа байвал шууд унагаана
        resp.raise_for_status()

    def _auth_headers(self, version: str = "3") -> Dict[str, str]:
        """Нэвтэрсэн session-д хэрэглэх нийтлэг header."""
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
    # Market data
    # ------------------------------------------------------------------
    def fetch_candles(
        self,
        epic: str,
        resolution: str = "H1",
        max_points: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Өгөгдсөн EPIC дээрх свеч-үүдийг татаж JSON list хэлбэрээр буцаана.

        Буцаах бүтэц:
        [
          {"time": "...", "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
          ...
        ]
        """
        if not self._authenticated:
            self.login()

        url = f"{self.base_url}/prices/{epic}"
        params = {
            "resolution": resolution,
            "max": max_points,
        }
        headers = self._auth_headers(version="3")

        resp = self.session.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        prices = data.get("prices", [])
        candles: List[Dict[str, Any]] = []

        for p in prices:
            t = p.get("snapshotTimeUTC") or p.get("snapshotTime")
            op = p.get("openPrice", {}) or {}
            hp = p.get("highPrice", {}) or {}
            lp = p.get("lowPrice", {}) or {}
            cp = p.get("closePrice", {}) or {}

            def _mid(x: Dict[str, Any]) -> float:
                b = x.get("bid")
                a = x.get("ask")
                if b is None and a is None:
                    return float(x.get("lastTraded", 0.0))
                if b is None:
                    return float(a)
                if a is None:
                    return float(b)
                return (float(b) + float(a)) / 2.0

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
    def get_candles(
        self,
        epic: str,
        resolution: str = "H1",
        max_points: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Хуучин кодтой нийцүүлэхийн тулд fetch_candles-ийн alias.

        analyzer.py, strategy.py гэх мэт хуучин файлууд
        ig.get_candles(...) гэж дууддаг тул эндээс шууд fetch_candles руу
        дамжуулж байна.
        """
        return self.fetch_candles(epic, resolution=resolution, max_points=max_points)
