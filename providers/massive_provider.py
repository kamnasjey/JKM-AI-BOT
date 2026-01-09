from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from providers.base import MarketDataProvider


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _parse_ts(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(v, (int, float)):
        sec = float(v)
        if sec > 1e12:
            sec = sec / 1000.0
        try:
            return datetime.fromtimestamp(sec, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


class MassiveProvider(MarketDataProvider):
    """Massive market data provider (legacy providers/* contract).

    Returns candles in the bot's expected schema:
    {time: datetime(UTC), open/high/low/close: float, volume?: float}

    Env:
    - MASSIVE_BASE_URL (required)
    - MASSIVE_API_KEY (required)
    - MASSIVE_CANDLES_PATH (default: /candles)
    - MASSIVE_TIMEOUT_S (default: 15)
    - MASSIVE_RETRIES (default: 3)
    - MASSIVE_MIN_DELAY_S (default: 0.2)
    - MASSIVE_AUTH_HEADER (default: Authorization)
    - MASSIVE_AUTH_PREFIX (default: Bearer)
    """

    def __init__(self) -> None:
        base_url = _env("MASSIVE_BASE_URL")
        if not base_url:
            raise RuntimeError("MASSIVE_BASE_URL not configured")
        self._base_url = base_url.rstrip("/")

        self._candles_path = _env("MASSIVE_CANDLES_PATH", "/candles")
        self._timeout_s = float(_env("MASSIVE_TIMEOUT_S", "15") or "15")
        self._retries = int(_env("MASSIVE_RETRIES", "3") or "3")
        self._min_delay_s = float(_env("MASSIVE_MIN_DELAY_S", "0.2") or "0.2")
        self._auth_header = _env("MASSIVE_AUTH_HEADER", "Authorization")
        self._auth_prefix = _env("MASSIVE_AUTH_PREFIX", "Bearer")

        key = _env("MASSIVE_API_KEY")
        if not key:
            raise RuntimeError("MASSIVE_API_KEY not configured")
        self._key = key

        self._session = requests.Session()
        self._last_call_at = 0.0

    def _rate_limit(self) -> None:
        now = time.time()
        wait = (self._last_call_at + float(self._min_delay_s)) - now
        if wait > 0:
            time.sleep(wait)
        self._last_call_at = time.time()

    def _headers(self) -> Dict[str, str]:
        # Never log these headers.
        if self._auth_header.lower() == "authorization":
            return {"Authorization": f"{self._auth_prefix} {self._key}"}
        return {self._auth_header: f"{self._auth_prefix} {self._key}"}

    def _extract_items(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for k in ("candles", "data", "results"):
                v = payload.get(k)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
        return []

    def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start_ts: Optional[datetime],
        end_ts: Optional[datetime],
        *,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        sym = str(symbol or "").strip().upper().replace("/", "").replace(" ", "")
        url = f"{self._base_url}{self._candles_path}"

        params: Dict[str, Any] = {"symbol": sym, "timeframe": str(timeframe), "limit": int(limit) if limit else None}
        params = {k: v for k, v in params.items() if v is not None}

        if start_ts is not None:
            if start_ts.tzinfo is None:
                start_ts = start_ts.replace(tzinfo=timezone.utc)
            params["start"] = start_ts.astimezone(timezone.utc).isoformat()
        if end_ts is not None:
            if end_ts.tzinfo is None:
                end_ts = end_ts.replace(tzinfo=timezone.utc)
            params["end"] = end_ts.astimezone(timezone.utc).isoformat()

        last_err: Optional[Exception] = None
        for attempt in range(max(1, int(self._retries))):
            try:
                self._rate_limit()
                resp = self._session.get(url, params=params, headers=self._headers(), timeout=float(self._timeout_s))
                resp.raise_for_status()
                payload = resp.json()
                items = self._extract_items(payload)

                out: List[Dict[str, Any]] = []
                for it in items:
                    ts = _parse_ts(it.get("time") or it.get("ts") or it.get("timestamp"))
                    if ts is None:
                        continue
                    try:
                        c: Dict[str, Any] = {
                            "time": ts,
                            "open": float(it.get("open")),
                            "high": float(it.get("high")),
                            "low": float(it.get("low")),
                            "close": float(it.get("close")),
                        }
                        if it.get("volume") is not None:
                            c["volume"] = float(it.get("volume"))
                        out.append(c)
                    except Exception:
                        continue

                out.sort(key=lambda x: x["time"])

                if start_ts is not None:
                    st = start_ts.astimezone(timezone.utc) if start_ts.tzinfo else start_ts.replace(tzinfo=timezone.utc)
                    out = [c for c in out if c["time"] >= st]
                if end_ts is not None:
                    et = end_ts.astimezone(timezone.utc) if end_ts.tzinfo else end_ts.replace(tzinfo=timezone.utc)
                    out = [c for c in out if c["time"] <= et]

                return out
            except Exception as e:
                last_err = e
                time.sleep(min(2.0 * (attempt + 1), 6.0))

        if last_err is not None:
            raise last_err
        return []

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "m5",
        limit: int = 100,
        since_ts: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        # Legacy contract: no explicit end_ts.
        return self.fetch_candles(symbol, timeframe, since_ts, None, limit=int(limit))

    def search_symbol(self, term: str) -> List[Dict[str, Any]]:
        t = str(term or "").strip().upper()
        if not t:
            return []
        # Massive search endpoint is not standardized; keep minimal.
        return [{"symbol": t, "description": ""}]
