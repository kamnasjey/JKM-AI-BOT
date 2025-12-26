# ig_client.py
"""
IG Markets REST API client – login хийж, candles татах.

ENV хувьсагчууд:
  IG_API_KEY
  IG_USERNAME
  IG_PASSWORD
  IG_ACCOUNT_ID
  IG_IS_DEMO = "true" / "false"  # demo=True бол demo-api, false бол live-api

    # Demo mode (ихэнх тохиолдолд тусдаа Web API demo login + тусдаа API key шаарддаг)
    IG_DEMO_API_KEY
    IG_DEMO_USERNAME
    IG_DEMO_PASSWORD
    IG_DEMO_ACCOUNT_ID  # optional

EPIC хувьсагчууд (pair бүрийн):
  EPIC_XAUUSD
  EPIC_EURJPY
  EPIC_GBPJPY
  ...

Эдгээрийг локал болон серверийн ENV дээрээ тохируулна.
"""

from __future__ import annotations

import os
import threading
import time
from collections import Counter, deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse


import logging
import requests
from requests import Response

from engine.utils.logging_utils import log_kv
import config

# Logger тохиргоо
logger = logging.getLogger(__name__)


class FetchPausedError(RuntimeError):
    """Raised when the IG fetch circuit breaker is open."""


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return default


_ig_call_source: ContextVar[str] = ContextVar("ig_call_source", default="unknown")


@contextmanager
def ig_call_source(name: str) -> Iterator[None]:
    token = _ig_call_source.set(name)
    try:
        yield
    finally:
        _ig_call_source.reset(token)


class _IGRequestStats:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.started_at = time.time()
            self.total = 0
            self.by_method: Counter[str] = Counter()
            self.by_path: Counter[str] = Counter()
            self.by_status: Counter[str] = Counter()
            self.by_source: Counter[str] = Counter()
            self.latency_ms_sum = 0.0
            self.latency_count = 0
            # Keep a small rolling window for last-60s rate calculation
            self._recent: Deque[Tuple[float, str]] = deque(maxlen=5000)  # (timestamp, source)

    def record(self, *, method: str, url: str, status: Optional[int], elapsed_ms: float, source: str) -> None:
        parsed = urlparse(url)
        path = parsed.path
        with self._lock:
            self.total += 1
            self.by_method[method.upper()] += 1
            self.by_path[path] += 1
            if status is not None:
                self.by_status[str(status)] += 1
            self.by_source[source] += 1
            self.latency_ms_sum += float(elapsed_ms)
            self.latency_count += 1
            now = time.time()
            self._recent.append((now, source))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            # purge >60s
            while self._recent and (now - self._recent[0][0]) > 60.0:
                self._recent.popleft()
            last_60s_total = len(self._recent)
            last_60s_by_source: Counter[str] = Counter([s for _, s in self._recent])

            elapsed = max(now - self.started_at, 1e-9)
            avg_latency = (self.latency_ms_sum / self.latency_count) if self.latency_count else 0.0

            return {
                "started_at": self.started_at,
                "elapsed_sec": elapsed,
                "total": self.total,
                "by_method": dict(self.by_method),
                "by_path": dict(self.by_path),
                "by_status": dict(self.by_status),
                "by_source": dict(self.by_source),
                "avg_latency_ms": avg_latency,
                "last_60s_total": last_60s_total,
                "last_60s_rps": last_60s_total / 60.0,
                "last_60s_by_source": dict(last_60s_by_source),
            }


_IG_STATS = _IGRequestStats()


def get_ig_request_stats(*, reset: bool = False) -> Dict[str, Any]:
    """Return a snapshot of IG HTTP request stats.

    If reset=True, returns the snapshot after resetting counters.
    """
    if reset:
        _IG_STATS.reset()
    return _IG_STATS.snapshot()



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
        self._wrap_session_for_metrics()
        self.cst: Optional[str] = None
        self.x_security_token: Optional[str] = None
        self._authenticated: bool = False

        # Retry/backoff + circuit breaker (market data fetches only)
        self._fetch_failures_consecutive: int = 0
        self._fetch_paused_until_ts: float = 0.0
        self._fetch_lock = threading.RLock()

    def _fetch_is_paused(self) -> bool:
        return time.time() < float(self._fetch_paused_until_ts)

    def _fetch_pause_seconds_remaining(self) -> int:
        remaining = int(self._fetch_paused_until_ts - time.time())
        return remaining if remaining > 0 else 0

    def _fetch_record_success(self) -> None:
        with self._fetch_lock:
            self._fetch_failures_consecutive = 0
            self._fetch_paused_until_ts = 0.0

    def _fetch_record_failure_and_maybe_pause(self, *, reason: str) -> None:
        with self._fetch_lock:
            self._fetch_failures_consecutive += 1
            fail_limit = int(getattr(config, "IG_FETCH_CB_FAILURES", 5) or 5)
            pause_min = int(getattr(config, "IG_FETCH_CB_PAUSE_MIN", 3) or 3)
            if self._fetch_failures_consecutive >= max(fail_limit, 1):
                pause_sec = max(pause_min, 1) * 60
                self._fetch_paused_until_ts = time.time() + pause_sec
                log_kv(
                    logger,
                    "FETCH_PAUSED",
                    source=_ig_call_source.get(),
                    failures=self._fetch_failures_consecutive,
                    pause_min=pause_min,
                    until=datetime.fromtimestamp(self._fetch_paused_until_ts, tz=timezone.utc).isoformat(),
                    reason=reason,
                )

    def _sleep_backoff(self, *, attempt: int, base: float, cap: float) -> None:
        delay = min(cap, base * (2.0 ** max(attempt - 1, 0)))
        # small deterministic jitter without random module
        jitter = (time.time() % 1.0) * 0.1
        time.sleep(delay + jitter)

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        timeout_sec: float,
        retry_attempts: int,
        backoff_base_sec: float,
        backoff_cap_sec: float,
        **kwargs: Any,
    ) -> Response:
        """Request wrapper for market-data fetches.

        Retries transient failures: 429, 5xx, and request timeouts.
        Applies a simple circuit breaker that pauses fetching after N consecutive failures.
        """
        if self._fetch_is_paused():
            raise FetchPausedError(
                f"IG fetch paused for ~{self._fetch_pause_seconds_remaining()}s"
            )

        last_exc: Optional[BaseException] = None
        for attempt in range(1, max(int(retry_attempts), 1) + 1):
            try:
                resp = self.session.request(method, url, timeout=timeout_sec, **kwargs)

                status = int(getattr(resp, "status_code", 0) or 0)
                transient = status == 429 or (500 <= status <= 599)

                if transient:
                    if attempt >= retry_attempts:
                        # Let caller handle via raise_for_status; record failure first.
                        self._fetch_record_failure_and_maybe_pause(reason=f"http_{status}")
                        return resp
                    self._sleep_backoff(attempt=attempt, base=backoff_base_sec, cap=backoff_cap_sec)
                    continue

                # Non-transient response.
                self._fetch_record_success()
                return resp

            except FetchPausedError:
                raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_exc = e
                if attempt >= retry_attempts:
                    self._fetch_record_failure_and_maybe_pause(reason=type(e).__name__)
                    raise
                self._sleep_backoff(attempt=attempt, base=backoff_base_sec, cap=backoff_cap_sec)
            except requests.exceptions.RequestException as e:
                # Most RequestExceptions aren't transient; do not loop forever.
                last_exc = e
                self._fetch_record_failure_and_maybe_pause(reason=type(e).__name__)
                raise

        # Should be unreachable, but keep mypy happy.
        if last_exc:
            raise last_exc
        raise RuntimeError("IG request failed")

    def _wrap_session_for_metrics(self) -> None:
        original_request = self.session.request

        def wrapped_request(method: str, url: str, **kwargs):
            start = time.perf_counter()
            source = _ig_call_source.get()
            status: Optional[int] = None
            try:
                resp = original_request(method, url, **kwargs)
                status = getattr(resp, "status_code", None)
                return resp
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                try:
                    _IG_STATS.record(
                        method=str(method),
                        url=str(url),
                        status=status,
                        elapsed_ms=elapsed_ms,
                        source=str(source),
                    )
                except Exception:
                    # Never break trading logic due to metrics.
                    pass

        self.session.request = wrapped_request  # type: ignore[method-assign]

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
        # Load .env if present (does not override existing process env by default).
        try:
            from dotenv import load_dotenv  # type: ignore

            load_dotenv()
        except Exception:
            pass

        # Demo mode uses IG's demo gateway. For many IG accounts, demo Web API requires
        # a *separate* demo username/password and a *separate* API key.

        if is_demo is None:
            is_demo_raw = os.getenv("IG_IS_DEMO", "false").strip().lower()
            # "true", "1", "yes" бол demo, бусад нь live-api гэж үзнэ
            is_demo_val = is_demo_raw in ("true", "1", "yes", "y")
        else:
            is_demo_val = is_demo

        if is_demo_val:
            api_key = os.getenv("IG_DEMO_API_KEY", "")
            username = os.getenv("IG_DEMO_USERNAME", "")
            password = os.getenv("IG_DEMO_PASSWORD", "")
            account_id = os.getenv("IG_DEMO_ACCOUNT_ID", "")
        else:
            api_key = os.getenv("IG_API_KEY", "")
            username = os.getenv("IG_USERNAME", "")
            password = os.getenv("IG_PASSWORD", "")
            account_id = os.getenv("IG_ACCOUNT_ID", "")

        if is_demo_val:
            if not api_key or not username or not password:
                raise RuntimeError(
                    "Demo ENV тохиргоо дутуу байна (IG_DEMO_API_KEY, IG_DEMO_USERNAME, IG_DEMO_PASSWORD заавал хэрэгтэй). "
                    "IG Portal дээрх 'Web API demo login details' хэсэгт demo username/password-оо үүсгээд, "
                    "дараа нь эдгээр env-үүдийг тохируулна."
                )
        else:
            if not api_key or not username or not password:
                raise RuntimeError(
                    "IG ENV тохиргоо дутуу байна (IG_API_KEY, IG_USERNAME, IG_PASSWORD заавал хэрэгтэй)."
                )

        # account_id is required for live by default; for demo we allow it to be empty and
        # continue with IG's default account.
        if not is_demo_val and not account_id:
            raise RuntimeError(
                "IG_ACCOUNT_ID тохиргоо дутуу байна (live mode дээр заавал хэрэгтэй). "
                "Demo ашиглаж байвал IG_DEMO_ACCOUNT_ID-г тохируулахгүй байсан ч болно."
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
        
        Validation & Normalization:
        - normalize_price_decimals()
        - choose_mid_price()
        - validate_epic()
        - Data integrity checks (High >= Low, etc.)
        """
        self.validate_epic(epic)

        if not self._authenticated:
            self.login()

        url = f"{self.base_url}/prices/{epic}"
        params = {
            "resolution": resolution,
            "max": str(max_points),
            "pageSize": str(max_points), # Try explicit pageSize too
        }
        # logger.debug(f"[IG-DEBUG] Fetching: {url} | Params: {params}")
        headers = self._auth_headers(version="3")

        retry_attempts = int(getattr(config, "IG_FETCH_RETRY_ATTEMPTS", 4) or 4)
        timeout_sec = float(getattr(config, "IG_FETCH_TIMEOUT_SEC", 20.0) or 20.0)
        backoff_base_sec = float(getattr(config, "IG_FETCH_BACKOFF_BASE_SEC", 0.5) or 0.5)
        backoff_cap_sec = float(getattr(config, "IG_FETCH_BACKOFF_CAP_SEC", 8.0) or 8.0)

        resp = self._request_with_retry(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout_sec=timeout_sec,
            retry_attempts=retry_attempts,
            backoff_base_sec=backoff_base_sec,
            backoff_cap_sec=backoff_cap_sec,
        )
        resp.raise_for_status()
        data = resp.json()

        prices = data.get("prices", [])
        return self._parse_ig_prices(epic=epic, prices=prices)

    def fetch_candles_range(
        self,
        epic: str,
        *,
        resolution: str,
        start: datetime,
        end: datetime,
        page_size: int = 1000,
        page_number: int = 1,
    ) -> List[Dict[str, Any]]:
        """Fetch candles for a specific time window.

        This is intended for backfill tools to reach older history than the default
        'latest N bars' endpoint behavior.
        """
        self.validate_epic(epic)
        if not self._authenticated:
            self.login()

        url = f"{self.base_url}/prices/{epic}"
        headers = self._auth_headers(version="3")

        start_utc = self._to_utc_dt(start)
        end_utc = self._to_utc_dt(end)
        # IG typically accepts ISO timestamps; we send UTC with trailing 'Z'.
        start_s = start_utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        end_s = end_utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

        retry_attempts = int(getattr(config, "IG_FETCH_RETRY_ATTEMPTS", 4) or 4)
        timeout_sec = float(getattr(config, "IG_FETCH_TIMEOUT_SEC", 20.0) or 20.0)
        backoff_base_sec = float(getattr(config, "IG_FETCH_BACKOFF_BASE_SEC", 0.5) or 0.5)
        backoff_cap_sec = float(getattr(config, "IG_FETCH_BACKOFF_CAP_SEC", 8.0) or 8.0)

        params = {
            "resolution": resolution,
            "from": start_s,
            "to": end_s,
            "pageSize": str(int(page_size)),
            "pageNumber": str(int(page_number)),
        }

        resp = self._request_with_retry(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout_sec=timeout_sec,
            retry_attempts=retry_attempts,
            backoff_base_sec=backoff_base_sec,
            backoff_cap_sec=backoff_cap_sec,
        )
        resp.raise_for_status()
        data = resp.json()
        prices = data.get("prices", [])
        return self._parse_ig_prices(epic=epic, prices=prices)

    def _to_utc_dt(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _parse_ig_prices(self, *, epic: str, prices: Any) -> List[Dict[str, Any]]:
        candles: List[Dict[str, Any]] = []
        if not isinstance(prices, list):
            return candles

        for p in prices:
            if not isinstance(p, dict):
                continue
            t_raw = p.get("snapshotTimeUTC") or p.get("snapshotTime")
            t = self._parse_ig_time(t_raw)
            op = p.get("openPrice", {}) or {}
            hp = p.get("highPrice", {}) or {}
            lp = p.get("lowPrice", {}) or {}
            cp = p.get("closePrice", {}) or {}

            open_mid = self.choose_mid_price(op.get("bid"), op.get("ask"), op.get("lastTraded"))
            high_mid = self.choose_mid_price(hp.get("bid"), hp.get("ask"), hp.get("lastTraded"))
            low_mid = self.choose_mid_price(lp.get("bid"), lp.get("ask"), lp.get("lastTraded"))
            close_mid = self.choose_mid_price(cp.get("bid"), cp.get("ask"), cp.get("lastTraded"))

            if high_mid < low_mid:
                logger.warning(
                    f"[DataAnomaly] High({high_mid}) < Low({low_mid}) at {t}. Swapping them. Epic={epic}"
                )
                high_mid, low_mid = low_mid, high_mid

            if max(open_mid, close_mid) > high_mid:
                high_mid = max(open_mid, close_mid, high_mid)

            if min(open_mid, close_mid) < low_mid:
                low_mid = min(open_mid, close_mid, low_mid)

            open_mid = self.normalize_price_decimals(open_mid)
            high_mid = self.normalize_price_decimals(high_mid)
            low_mid = self.normalize_price_decimals(low_mid)
            close_mid = self.normalize_price_decimals(close_mid)

            candles.append(
                {
                    "time": t,
                    "open": open_mid,
                    "high": high_mid,
                    "low": low_mid,
                    "close": close_mid,
                }
            )

        return candles

    def _parse_ig_time(self, value: Any) -> datetime:
        """Parse IG snapshotTime/snapshotTimeUTC into tz-aware UTC datetime.

        IG has been observed returning either ISO-8601 or 'YYYY/MM/DD HH:MM:SS'.
        """
        if isinstance(value, datetime):
            dt = value
        else:
            s = str(value or "").strip()
            if not s:
                return datetime.now(timezone.utc)

            # Common case: ISO-8601 with optional Z
            try:
                s2 = s.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s2)
            except Exception:
                # Fallbacks
                dt = None  # type: ignore[assignment]
                for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(s, fmt)
                        break
                    except Exception:
                        continue
                if dt is None:
                    # Last resort: now
                    return datetime.now(timezone.utc)

        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    # ------------------------------------------------------------------
    # Helper functions (Fix Plan)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Helper functions (Fixed for Data Quality)
    # ------------------------------------------------------------------
    def validate_epic(self, epic: str) -> None:
        """
        EPIC зөв эсэхийг шалгах. 300-500 pip зөрүү нь:
        1. Буруу instrument (Futures vs Cash).
        2. Буруу зах зээл (Wall St vs US Tech).
        3. Demo vs Live feed зөрүү.
        """
        if not epic:
            logger.warning("[IG] Empty EPIC provided!")
            return
        
        # 1. Basic Format Check
        if "." not in epic:
             logger.warning(f"[IG] Suspicious EPIC format: '{epic}'. Expecting dots (e.g. CS.D.EURUSD.TODAY.IP)")

        # 2. CFDs usually start with CS.D or IX.D
        if not (epic.startswith("CS.D") or epic.startswith("IX.D") or epic.startswith("KA.D")):
            # Just a warning, as some valid epics might differ
            logger.info(f"[IG] Note: EPIC '{epic}' does not start with standard CS.D/IX.D prefixes.")

        # 3. Time Validity
        # "TODAY", "DAILY", "JUN-24" etc.
        # If user wants Spot, they should usually look for "TODAY" or "IP" (Cash).
        # Futures often have month codes.
        if "JUN" in epic or "SEP" in epic or "DEC" in epic or "MAR" in epic:
             logger.warning(f"[IG] EPIC '{epic}' appears to be a Futures contract (Quarterly). Price may differ from Spot by spread/premium.")

        logger.info(f"[IG] Validating EPIC: {epic} OK")

    def normalize_price_decimals(self, price: float) -> float:
        """
        Smart Normalization based on Price Level (Heuristic).
        
        - Price > 500  (Gold, Indices, BTC) -> 2 decimals (e.g. 2034.50)
        - Price > 20   (Oil, Silver, JPY)   -> 3 decimals (e.g. 145.234)
        - Price < 20   (Forex Majors)       -> 5 decimals (e.g. 1.05234)
        """
        if price is None:
            return 0.0
        
        try:
            val = float(price)
            if val > 500:
                return round(val, 2)
            elif val > 20:
                return round(val, 3)
            else:
                return round(val, 5)
        except Exception:
            return 0.0

    def choose_mid_price(self, bid: Any, ask: Any, last_traded: Any) -> float:
        """
        Robust Mid Price Calculation.
        Returns 0.0 if absolutely no data.
        """
        try:
            b = float(bid) if bid is not None else None
            a = float(ask) if ask is not None else None
            l = float(last_traded) if last_traded is not None else None
            
            # 1. Try Bid/Ask Mid
            if b is not None and a is not None:
                # Sanity: if spread is huge?
                mid = (b + a) / 2.0
                spread = abs(a - b)
                
                # Check for bad data (e.g. Ask=0 or Bid=0 or abnormally wide)
                # If price is ~2000 (Gold), 0.1% is 2.0. Spread should be ~0.3-0.5.
                # If spread > 1% of price, it's suspicious liquidty or bad data.
                if mid > 0 and (spread / mid) > 0.01: 
                    logger.warning(f"[IG] Wide Spread detected: Bid={b}, Ask={a}, Spread={spread}. Using Mid anyway.")
                
                return mid
            
            # 2. Fallback to single side
            if b is not None: return b
            if a is not None: return a
            
            # 3. Fallback to Last Traded
            if l is not None:
                return l
                
            return 0.0
        except ValueError:
            return 0.0


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
