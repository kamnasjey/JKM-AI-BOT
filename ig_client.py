# ig_client.py
import os
from typing import List, Dict

import requests


class IGClient:
    """
    IG Markets REST API-тай холбогдож,
    login хийж, candles (үнэ) татдаг энгийн client.
    """

    def __init__(
        self,
        api_key: str,
        username: str,
        password: str,
        account_id: str,
        is_demo: bool = True,
    ) -> None:
        self.api_key = api_key
        self.username = username
        self.password = password
        self.account_id = account_id
        self.is_demo = is_demo

        # Demo эсвэл live endpoint
        self.base_url = (
            "https://demo-api.ig.com/gateway/deal"
            if is_demo
            else "https://api.ig.com/gateway/deal"
        )

        self.session = requests.Session()
        self.cst: str | None = None
        self.xst: str | None = None

    # ------------ ENV-ээс унших factory ------------
    @classmethod
    def from_env(cls, is_demo: bool = True) -> "IGClient":
        api_key = os.getenv("IG_API_KEY", "")
        username = os.getenv("IG_USERNAME", "")
        password = os.getenv("IG_PASSWORD", "")
        account_id = os.getenv("IG_ACCOUNT_ID", "")

        if not all([api_key, username, password, account_id]):
            raise RuntimeError(
                "IG env хувьсагч дутуу байна. "
                "IG_API_KEY, IG_USERNAME, IG_PASSWORD, IG_ACCOUNT_ID бүгд хэрэгтэй."
            )

        return cls(
            api_key=api_key,
            username=username,
            password=password,
            account_id=account_id,
            is_demo=is_demo,
        )

    # ------------ LOGIN ------------
    def login(self) -> None:
        url = self.base_url + "/session"

        headers = {
            "X-IG-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Version": "2",
        }

        payload = {
            "identifier": self.username,
            "password": self.password,
        }

        resp = self.session.post(url, json=payload, headers=headers)

        # Debug мэдээлэл – 403, 401 г.м шалтгааныг харах гэж
        print("IG login status:", resp.status_code)
        print("IG login body  :", resp.text)

        if not resp.ok:
            # HTTPError шидэхийн оронд ойлгомжтой RuntimeError шидье
            raise RuntimeError(f"IG login failed: {resp.status_code} {resp.text}")

        self.cst = resp.headers.get("CST")
        self.xst = resp.headers.get("X-SECURITY-TOKEN")

        if not self.cst or not self.xst:
            raise RuntimeError(
                "IG login succeeded but CST/X-SECURITY-TOKEN headers алга байна."
            )

    # ------------ CANDLES ТАТАХ ------------
    def get_candles(
        self, epic: str, resolution: str, max_points: int = 100
    ) -> List[Dict]:
        """
        epic: IG instrument EPIC код (ж: CS.D.GOLD.CFD.IP)
        resolution: MINUTE_15, HOUR_1, DAY гэх мэт
        """
        if self.cst is None or self.xst is None:
            self.login()

        url = self.base_url + f"/prices/{epic}"
        params = {
            "resolution": resolution,
            "max": max_points,
        }

        headers = {
            "X-IG-API-KEY": self.api_key,
            "CST": self.cst,
            "X-SECURITY-TOKEN": self.xst,
            "Accept": "application/json",
            "Version": "3",
        }

        resp = self.session.get(url, params=params, headers=headers)
        print("IG prices status:", resp.status_code)

        if not resp.ok:
            raise RuntimeError(
                f"IG get prices failed: {resp.status_code} {resp.text}"
            )

        data = resp.json()
        prices = data.get("prices", [])

        candles: List[Dict] = []

        for p in prices:
            t = p.get("snapshotTimeUTC") or p.get("snapshotTime")
            op = p["openPrice"]
            hp = p["highPrice"]
            lp = p["lowPrice"]
            cp = p["closePrice"]

            def mid(field: Dict[str, str]) -> float:
                return (float(field["bid"]) + float(field["ask"])) / 2.0

            candles.append(
                {
                    "time": t,
                    "open": mid(op),
                    "high": mid(hp),
                    "low": mid(lp),
                    "close": mid(cp),
                }
            )

        return candles
    # ------------ MARKET SEARCH (EPIC олох) ------------
    def search_markets(self, search_term: str):
        """
        IG-ийн /markets endpoint-ээр searchTerm-аар хайгаад
        EPIC-үүдийг буцаана.
        """
        if self.cst is None or self.xst is None:
            self.login()

        url = self.base_url + "/markets"
        params = {"searchTerm": search_term}

        headers = {
            "X-IG-API-KEY": self.api_key,
            "CST": self.cst,
            "X-SECURITY-TOKEN": self.xst,
            "Accept": "application/json",
            "Version": "1",
        }

        resp = self.session.get(url, params=params, headers=headers)
        print("IG search status:", resp.status_code)

        if not resp.ok:
            raise RuntimeError(
                f"IG search failed: {resp.status_code} {resp.text}"
            )

        data = resp.json()
        return data.get("markets", [])
