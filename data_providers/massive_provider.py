from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

from .base import DataProvider
from .models import Candle
from .normalize import normalize_candles

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _dt_to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _dt_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class MassiveConfig:
    base_url: str
    candles_path: str
    ref_path: str
    ref_ticker_param: str
    ref_ok_key: str
    timeout_s: float
    retries: int
    min_delay_s: float
    auth_header: str
    auth_prefix: str


_FOREX_AND_METALS: set[str] = {
    "EURUSD",
    "USDJPY",
    "GBPUSD",
    "AUDUSD",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
    "AUDJPY",
    "EURAUD",
    "EURCHF",
    "XAUUSD",
}

_CRYPTO: set[str] = {"BTCUSD"}


def _canon_tf(timeframe: str) -> str:
    tf = str(timeframe or "").strip().lower()
    if tf in {"5m", "m5", "minute_5"}:
        return "m5"
    if tf in {"15m", "m15", "minute_15"}:
        return "m15"
    if tf in {"1h", "h1", "hour"}:
        return "h1"
    if tf in {"4h", "h4", "hour_4"}:
        return "h4"
    if tf in {"1d", "d1", "day"}:
        return "d1"
    return tf or "m5"


def to_massive_ticker(internal_symbol: str) -> str:
    """Map internal symbol to Massive ticker.

    Rule (explicit, no guessing):
    - Forex + Gold: C:SYMBOL
    - Crypto: X:SYMBOL
    Only the configured 15 instruments are accepted.
    """

    sym = str(internal_symbol or "").strip().upper().replace("/", "").replace(" ", "")
    if sym in _FOREX_AND_METALS:
        return f"C:{sym}"
    if sym in _CRYPTO:
        return f"X:{sym}"
    raise ValueError(f"Unsupported symbol for Massive mapping: {sym}")


class MassiveDataProvider(DataProvider):
    """Massive OHLC provider.

    This implementation is intentionally configurable because Massive API shapes
    can vary. Configure via env vars (no secrets are logged):

    - MASSIVE_BASE_URL (e.g. https://api.massive.example)
    - MASSIVE_CANDLES_PATH
        - default: /v2/aggs/ticker (Polygon-style aggregates)
        - set to /candles to use the legacy query-param style
    - MASSIVE_TIMEOUT_S (default: 15)
    - MASSIVE_RETRIES (default: 3)
    - MASSIVE_MIN_DELAY_S (default: 0.2)
    - MASSIVE_AUTH_HEADER (default: Authorization)
    - MASSIVE_AUTH_PREFIX (default: Bearer)

    Expected response (any of these):
    - list of candle dicts
    - {"candles": [...]} or {"data": [...]} wrapping

    Each candle dict should include: time|ts|timestamp, open, high, low, close, (optional volume)
    with time in ISO8601 or unix seconds/ms.
    """

    name = "MASSIVE"

    def __init__(self, *, config: Optional[MassiveConfig] = None):
        if config is None:
            base_url = _env("MASSIVE_BASE_URL", "https://api.massive.com")
            config = MassiveConfig(
                base_url=base_url.rstrip("/"),
                candles_path=_env("MASSIVE_CANDLES_PATH", "/v2/aggs/ticker"),
                ref_path=_env("MASSIVE_REF_PATH", ""),
                ref_ticker_param=_env("MASSIVE_REF_TICKER_PARAM", "ticker"),
                ref_ok_key=_env("MASSIVE_REF_OK_KEY", "results"),
                timeout_s=_env_float("MASSIVE_TIMEOUT_S", 15.0),
                retries=_env_int("MASSIVE_RETRIES", 3),
                min_delay_s=_env_float("MASSIVE_MIN_DELAY_S", 0.2),
                auth_header=_env("MASSIVE_AUTH_HEADER", "Authorization"),
                auth_prefix=_env("MASSIVE_AUTH_PREFIX", "Bearer"),
            )

        self._cfg = config
        self._key = _env("MASSIVE_API_KEY")
        if not self._key:
            raise RuntimeError("MASSIVE_API_KEY not configured")

        self._session = requests.Session()
        self._last_call_at = 0.0

    def normalize_symbol(self, symbol: str) -> str:
        raw = str(symbol or "").strip().upper().replace("/", "").replace(" ", "")
        # If already a Massive ticker (C:..., X:...), keep it.
        if ":" in raw and raw.split(":", 1)[0] in {"C", "X"}:
            return raw
        return to_massive_ticker(raw)

    def validate_ticker_exists(self, massive_ticker: str) -> Optional[bool]:
        """Best-effort ticker existence check.

        Returns:
            True/False if ref endpoint is configured and request succeeds,
            None if ref endpoint is not configured.

        Env vars:
            MASSIVE_REF_PATH: path under base_url (e.g. /v3/reference/tickers)
            MASSIVE_REF_TICKER_PARAM: query param name (default: ticker)
            MASSIVE_REF_OK_KEY: JSON key containing list results (default: results)

        Secrets are never logged.
        """

        if not self._cfg.ref_path:
            return None

        url = f"{self._cfg.base_url}{self._cfg.ref_path}"
        params = {str(self._cfg.ref_ticker_param): str(massive_ticker)}
        try:
            self._rate_limit()
            resp = self._session.get(url, params=params, headers=self._headers(), timeout=float(self._cfg.timeout_s))
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return False

        if isinstance(payload, dict):
            v = payload.get(str(self._cfg.ref_ok_key))
            if isinstance(v, list):
                return len(v) > 0
            # Some APIs return {"ok": true}
            ok = payload.get("ok")
            if isinstance(ok, bool):
                return ok
        if isinstance(payload, list):
            return len(payload) > 0
        return False

    def _rate_limit(self) -> None:
        # naive per-process minimum spacing
        now = time.time()
        wait = (self._last_call_at + float(self._cfg.min_delay_s)) - now
        if wait > 0:
            time.sleep(wait)
        self._last_call_at = time.time()

    def _headers(self) -> Dict[str, str]:
        # Never log these headers.
        if self._cfg.auth_header.lower() == "authorization":
            return {"Authorization": f"{self._cfg.auth_prefix} {self._key}"}
        return {self._cfg.auth_header: f"{self._cfg.auth_prefix} {self._key}"}

    def _parse_ts(self, v: Any) -> Optional[datetime]:
        if v is None:
            return None
        if isinstance(v, datetime):
            dt = v
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        if isinstance(v, (int, float)):
            # interpret >1e12 as ms
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

    def _extract_candles_list(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [c for c in payload if isinstance(c, dict)]
        if isinstance(payload, dict):
            for key in ("candles", "data", "results"):
                v = payload.get(key)
                if isinstance(v, list):
                    return [c for c in v if isinstance(c, dict)]
        return []

    def _tf_to_aggs(self, tf: str) -> tuple[int, str]:
        """Map canonical tf to Polygon-style (multiplier, timespan)."""

        tfc = _canon_tf(tf)
        if tfc == "m5":
            return (5, "minute")
        if tfc == "m15":
            return (15, "minute")
        if tfc == "h1":
            return (1, "hour")
        if tfc == "h4":
            return (4, "hour")
        if tfc == "d1":
            return (1, "day")
        # Default: treat unknown as minutes with multiplier 5
        return (5, "minute")

    def fetch_candles(
        self,
        symbol: str,
        *,
        timeframe: str = "m5",
        max_count: int = 100,
        limit: Optional[int] = None,
        since_ts: Optional[datetime] = None,
        until_ts: Optional[datetime] = None,
    ) -> List[Candle]:
        eff_limit = int(limit) if limit is not None else int(max_count)
        massive_ticker = self.normalize_symbol(symbol)
        tf = _canon_tf(timeframe)

        # Default to Polygon-style aggregates endpoint (C:/X: tickers).
        # Keep legacy /candles mode as an env override for compatibility.
        candles_path = str(self._cfg.candles_path or "").strip() or "/v2/aggs/ticker"
        is_legacy_candles = candles_path.rstrip("/").endswith("/candles")

        if until_ts is None:
            until_ts = datetime.now(timezone.utc)

        url: str
        params: Dict[str, Any]
        if is_legacy_candles:
            url = f"{self._cfg.base_url}{candles_path}"
            params = {
                "symbol": massive_ticker,
                "timeframe": str(tf),
                "limit": int(eff_limit),
            }
            if since_ts is not None:
                params["start"] = _dt_to_iso(since_ts)
            if until_ts is not None:
                params["end"] = _dt_to_iso(until_ts)
        else:
            mult, span = self._tf_to_aggs(tf)
            if since_ts is None:
                # Best-effort: infer start from limit.
                seconds_per_bar = {
                    "minute": 60,
                    "hour": 3600,
                    "day": 86400,
                }.get(span, 60) * max(1, int(mult))
                since_ts = until_ts - timedelta(seconds=int(eff_limit) * int(seconds_per_bar))

            start_ms = _dt_to_ms(since_ts)
            end_ms = _dt_to_ms(until_ts)
            base = candles_path.rstrip("/")
            url = f"{self._cfg.base_url}{base}/{massive_ticker}/range/{int(mult)}/{span}/{start_ms}/{end_ms}"
            params = {
                "adjusted": "true",
                # Use newest-first so incremental/backfill runs can append beyond meta.last_ts.
                "sort": "desc",
                "limit": int(eff_limit),
            }

        last_err: Optional[Exception] = None
        for attempt in range(max(1, int(self._cfg.retries))):
            try:
                self._rate_limit()
                resp = self._session.get(
                    url,
                    params=params,
                    headers=self._headers(),
                    timeout=float(self._cfg.timeout_s),
                )
                resp.raise_for_status()
                payload = resp.json()
                raw: List[Dict[str, Any]] = []

                if is_legacy_candles:
                    items = self._extract_candles_list(payload)
                    for it in items:
                        ts = self._parse_ts(it.get("time") or it.get("ts") or it.get("timestamp"))
                        if ts is None:
                            continue
                        try:
                            raw.append(
                                {
                                    "time": ts,
                                    "open": float(it.get("open")),
                                    "high": float(it.get("high")),
                                    "low": float(it.get("low")),
                                    "close": float(it.get("close")),
                                    **({"volume": it.get("volume")} if it.get("volume") is not None else {}),
                                }
                            )
                        except Exception:
                            continue
                else:
                    # Polygon-style aggregates: {"results": [{"t": ms, "o":..., "h":..., "l":..., "c":..., "v":...}, ...]}
                    items = []
                    if isinstance(payload, dict):
                        v = payload.get("results")
                        if isinstance(v, list):
                            items = [x for x in v if isinstance(x, dict)]

                    for it in items:
                        ts = self._parse_ts(it.get("t") or it.get("time") or it.get("ts") or it.get("timestamp"))
                        if ts is None:
                            continue
                        try:
                            raw.append(
                                {
                                    "time": ts,
                                    "open": float(it.get("o")),
                                    "high": float(it.get("h")),
                                    "low": float(it.get("l")),
                                    "close": float(it.get("c")),
                                    **({"volume": it.get("v")} if it.get("v") is not None else {}),
                                }
                            )
                        except Exception:
                            continue

                if since_ts is not None:
                    raw = [c for c in raw if c.get("time") and c["time"] > since_ts]
                if until_ts is not None:
                    raw = [c for c in raw if c.get("time") and c["time"] <= until_ts]

                # normalize_candles expects list[dict], but tolerates datetime `time`.
                return normalize_candles(
                    raw,
                    provider=self.name,
                    symbol=str(symbol).upper(),
                    timeframe=str(tf),
                    requested_limit=eff_limit,
                )
            except Exception as e:
                last_err = e
                # Simple backoff; do not log secrets.
                time.sleep(min(2.0 * (attempt + 1), 6.0))
                continue

        if last_err is not None:
            raise last_err
        return []
