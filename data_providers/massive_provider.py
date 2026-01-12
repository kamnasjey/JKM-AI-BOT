from __future__ import annotations

import os
import time
import logging
import random
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


def _sleep_backoff_s(attempt: int, *, base: float = 0.5, cap: float = 12.0) -> float:
    # Exponential backoff with jitter.
    raw = min(cap, base * (2 ** max(0, int(attempt))))
    return max(0.0, raw * (0.7 + (random.random() * 0.6)))


def _retry_after_s(resp: requests.Response) -> Optional[float]:
    """Parse Retry-After header (seconds or HTTP-date)."""
    try:
        ra = (resp.headers.get("Retry-After") or "").strip()
        if not ra:
            return None
        # Most providers return integer seconds.
        if ra.isdigit():
            return float(int(ra))
        # HTTP-date parsing is intentionally omitted (keep deps minimal).
        return None
    except Exception:
        return None


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
    page_limit: int


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
                page_limit=_env_int("MASSIVE_PAGE_LIMIT", 500),
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

    def _tf_seconds(self, tf: str) -> int:
        tfc = _canon_tf(tf)
        if tfc.startswith("m") and tfc[1:].isdigit():
            return int(tfc[1:]) * 60
        if tfc.startswith("h") and tfc[1:].isdigit():
            return int(tfc[1:]) * 3600
        if tfc.startswith("d") and tfc[1:].isdigit():
            return int(tfc[1:]) * 86400
        # fallback to 5m
        return 300

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

        if since_ts is not None:
            if since_ts.tzinfo is None:
                since_ts = since_ts.replace(tzinfo=timezone.utc)
            since_ts = since_ts.astimezone(timezone.utc)
        if until_ts.tzinfo is None:
            until_ts = until_ts.replace(tzinfo=timezone.utc)
        until_ts = until_ts.astimezone(timezone.utc)

        def _fetch_once(
            *,
            start: Optional[datetime],
            end: datetime,
            per_request_limit: int,
        ) -> List[Candle]:
            url: str
            params: Dict[str, Any]

            if is_legacy_candles:
                url = f"{self._cfg.base_url}{candles_path}"
                params = {
                    "symbol": massive_ticker,
                    "timeframe": str(tf),
                    "limit": int(per_request_limit),
                }
                if start is not None:
                    params["start"] = _dt_to_iso(start)
                params["end"] = _dt_to_iso(end)
            else:
                mult, span = self._tf_to_aggs(tf)
                use_start = start
                if use_start is None:
                    # Best-effort: infer start from limit.
                    # Use a wider window than N*tf to tolerate provider gaps/delays while
                    # still returning only `limit` bars (most recent, due to sort=desc).
                    use_start = end - timedelta(seconds=int(per_request_limit) * int(self._tf_seconds(tf)) * 4)
                start_ms = _dt_to_ms(use_start)
                end_ms = _dt_to_ms(end)
                base = candles_path.rstrip("/")
                url = f"{self._cfg.base_url}{base}/{massive_ticker}/range/{int(mult)}/{span}/{start_ms}/{end_ms}"
                params = {
                    "adjusted": "true",
                    # Prefer newest-first so small `limit` calls return the most recent bars.
                    # Normalization sorts ascending afterward.
                    "sort": "desc",
                    "limit": int(per_request_limit),
                    # Polygon.io uses apiKey as query parameter
                    "apiKey": self._key,
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
                    if resp.status_code == 429:
                        wait_s = _retry_after_s(resp)
                        if wait_s is None:
                            wait_s = _sleep_backoff_s(attempt, base=0.8, cap=20.0)
                        logger.warning(
                            "MASSIVE_HTTP_RETRY status=429 attempt=%d wait_s=%.2f symbol=%s tf=%s",
                            int(attempt + 1),
                            float(wait_s),
                            str(symbol).upper(),
                            str(tf),
                        )
                        time.sleep(wait_s)
                        continue

                    # Retry 5xx with backoff.
                    if 500 <= int(resp.status_code) <= 599:
                        wait_s = _sleep_backoff_s(attempt, base=0.6, cap=12.0)
                        logger.warning(
                            "MASSIVE_HTTP_RETRY status=%d attempt=%d wait_s=%.2f symbol=%s tf=%s",
                            int(resp.status_code),
                            int(attempt + 1),
                            float(wait_s),
                            str(symbol).upper(),
                            str(tf),
                        )
                        time.sleep(wait_s)
                        continue

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

                    if start is not None:
                        raw = [c for c in raw if c.get("time") and c["time"] >= start]
                    raw = [c for c in raw if c.get("time") and c["time"] <= end]

                    normalized = normalize_candles(
                        raw,
                        provider=self.name,
                        symbol=str(symbol).upper(),
                        timeframe=str(tf),
                        requested_limit=per_request_limit,
                    )
                    # Ensure callers always get ascending candles.
                    return sorted(normalized, key=lambda c: c.ts)
                except Exception as e:
                    last_err = e
                    time.sleep(_sleep_backoff_s(attempt, base=0.4, cap=6.0))
                    continue

            if last_err is not None:
                raise last_err
            return []

        # If caller specified a range, page over the range to overcome per-request caps.
        if since_ts is not None:
            page_limit = max(50, int(self._cfg.page_limit))
            bar_s = self._tf_seconds(tf)
            window = timedelta(seconds=int(bar_s) * int(page_limit))

            out: List[Candle] = []
            cur = since_ts
            # Walk forward in time; each request is bounded by window and capped by page_limit.
            while cur < until_ts:
                nxt = min(until_ts, cur + window)
                out.extend(_fetch_once(start=cur, end=nxt, per_request_limit=page_limit))
                # Advance by window; safety to avoid infinite loops.
                if nxt <= cur:
                    break
                cur = nxt

            # Deduplicate + sort (normalize already sorts asc, but across pages we recheck)
            by_ts: Dict[datetime, Candle] = {c.ts: c for c in out}
            merged = [by_ts[t] for t in sorted(by_ts.keys())]

            # If caller asked for a specific count (e.g. warmup), trim from the end.
            if eff_limit and len(merged) > eff_limit:
                merged = merged[-int(eff_limit) :]
            return merged

        # No explicit since_ts: fetch once based on limit.
        return _fetch_once(start=None, end=until_ts, per_request_limit=max(1, int(eff_limit)))
