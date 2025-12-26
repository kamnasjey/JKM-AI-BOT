# config.py
"""
Тохиргооны төв файл.

Telegram болон арилжааны үндсэн тохиргоонуудыг эндээс удирдана.
Нууц мэдээллүүдийг Render / .env дээрээс ENV хувьсагчаар уншина.

Заавал ENV дээр тавих хувьсагчууд:
  TELEGRAM_BOT_TOKEN  -> BotFather-аас авсан Telegram ботын токен

Сонголтоор:
  DEFAULT_CHAT_ID     -> Зарим мессежийг заавал энэ chat руу илгээх бол
  ADMIN_USER_ID       -> Админ хэрэглэгчийн Telegram user id
  AUTO_SCAN_INTERVAL_MIN -> Авто скан давтамж (минут)
"""

import os


def _get_int_env(name: str, default: int) -> int:
    """
    ENV хувьсагчаас int утга авах, байхгүй эсвэл буруу байвал default-оо буцаана.
    """
    val = os.getenv(name)
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _get_float_env(name: str, default: float) -> float:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or str(val).strip() == "":
        return default
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


# --- Telegram тохиргоо ---

# Render / .env дээр:
# TELEGRAM_BOT_TOKEN=7696542:....
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Хэрвээ DEFAULT_CHAT_ID-г тогтоосон бол зарим үед chat_id дамжуулахгүйгээр
# шууд энэ чат руу илгээж болно. Тохируулаагүй бол 0 хэвээр үлдэнэ.
DEFAULT_CHAT_ID: int = _get_int_env("DEFAULT_CHAT_ID", 0)

# Админы ID – эрх нээх, log авах гэх мэт.
# ENV дээр ADMIN_USER_ID тавибал тэрийг, үгүй бол доорх default-ыг ашиглана.
ADMIN_USER_ID: int = _get_int_env("ADMIN_USER_ID", 1445509840)

# Notification routing mode (Telegram):
# - "off": never send messages (dry-run)
# - "all": send normally
# - "admin_only": send only to ADMIN_CHAT_ID (or DEFAULT_CHAT_ID/ADMIN_USER_ID fallback)
NOTIFY_MODE: str = os.getenv("NOTIFY_MODE", "all").strip().lower()

# Admin chat id for Telegram sends in admin_only mode.
# Defaults to DEFAULT_CHAT_ID (if set) else ADMIN_USER_ID.
ADMIN_CHAT_ID: int = _get_int_env("ADMIN_CHAT_ID", int(DEFAULT_CHAT_ID or ADMIN_USER_ID))

# Вэб дээр ашиглах админы default credential (ENV-ээс солих шаардлагатай)
DEFAULT_ADMIN_EMAIL: str = os.getenv("DEFAULT_ADMIN_EMAIL", "")
DEFAULT_ADMIN_PASSWORD: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "")
DEFAULT_ADMIN_NAME: str = os.getenv("DEFAULT_ADMIN_NAME", "JKM Admin")
DEFAULT_ADMIN_TELEGRAM: str = os.getenv("DEFAULT_ADMIN_TELEGRAM", "")

# Вэб landing дээр харуулах холбоо барих мэдээлэл
PUBLIC_TELEGRAM_URL: str = os.getenv("PUBLIC_TELEGRAM_URL", "https://t.me/jkm_trading_ai_bot")
PUBLIC_SUPPORT_EMAIL: str = os.getenv("PUBLIC_SUPPORT_EMAIL", "support@jkm-ai.com")

# Вэб сешний хугацаа (минут)
WEB_SESSION_TTL_MINUTES: int = _get_int_env("WEB_SESSION_TTL_MINUTES", 720)


# --- Арилжааны үндсэн тохиргоо ---

# Market data source selection.
# - "simulation" (default): run the full app without any external market-data API.
# - "ig": use IG for candles (requires IG_* / IG_DEMO_* env vars).
MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "simulation").strip().lower()

# Автомат / гар скан хийх хослолууд
WATCH_PAIRS = [
    "XAUUSD",
    "EURJPY",
    "GBPJPY",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "EURUSD",
]

# Авто скан хийх timeframe (5 минут тутам M5)
AUTO_TIMEFRAME = "M5"

# Гар аргаар 'Pair хайх' дээр ашиглах timeframe
MANUAL_TIMEFRAME = "M15"

# Авто скан давтамж (минут)
AUTO_SCAN_INTERVAL_MIN: int = _get_int_env("AUTO_SCAN_INTERVAL_MIN", 5)


# --- APScheduler hardening (24/7) ---

# When the app is paused (CPU stall / deploy / sleep), APScheduler may "misfire".
# We allow a grace window to run the latest missed scan (coalesced) instead of
# backlogging multiple runs.
SCHEDULER_MISFIRE_GRACE_SEC: int = _get_int_env("SCHEDULER_MISFIRE_GRACE_SEC", 120)


# --- IG fetch hardening (retry + circuit breaker) ---

# Retries are for transient errors: 429, 5xx, and timeouts.
IG_FETCH_RETRY_ATTEMPTS: int = _get_int_env("IG_FETCH_RETRY_ATTEMPTS", 4)
IG_FETCH_TIMEOUT_SEC: float = _get_float_env("IG_FETCH_TIMEOUT_SEC", 20.0)
IG_FETCH_BACKOFF_BASE_SEC: float = _get_float_env("IG_FETCH_BACKOFF_BASE_SEC", 0.5)
IG_FETCH_BACKOFF_CAP_SEC: float = _get_float_env("IG_FETCH_BACKOFF_CAP_SEC", 8.0)

# Circuit breaker: after N consecutive failures, pause fetches for X minutes.
IG_FETCH_CB_FAILURES: int = _get_int_env("IG_FETCH_CB_FAILURES", 5)
IG_FETCH_CB_PAUSE_MIN: int = _get_int_env("IG_FETCH_CB_PAUSE_MIN", 3)


# --- Signal state (persistence) ---

# Cooldown window in minutes (persistent; survives restarts).
SIGNAL_COOLDOWN_MINUTES: int = _get_int_env("SIGNAL_COOLDOWN_MINUTES", 30)

# Max number of signals per symbol per day (0 disables the limit).
DAILY_LIMIT_PER_SYMBOL: int = _get_int_env("DAILY_LIMIT_PER_SYMBOL", 20)

# When multiple strategies produce candidates and the best one is blocked by governance
# (cooldown/daily limit), try the next-best candidate instead.
STRATEGY_FAILOVER_ON_BLOCK: bool = _get_bool_env("STRATEGY_FAILOVER_ON_BLOCK", True)


# --- Performance guards (24/7) ---

# If any single detector exceeds this runtime, log PERF_WARN.
DETECTOR_WARN_MS: int = _get_int_env("DETECTOR_WARN_MS", 50)

# If feature/primitives build exceeds this runtime, log PERF_WARN.
FEATURE_WARN_MS: int = _get_int_env("FEATURE_WARN_MS", 80)

# If a single pair scan exceeds this runtime, log PERF_WARN.
PAIR_WARN_MS: int = _get_int_env("PAIR_WARN_MS", 200)

# If an entire scan cycle exceeds this runtime, log PERF_WARN.
SCAN_CYCLE_WARN_MS: int = _get_int_env("SCAN_CYCLE_WARN_MS", 2000)

# Emit PERF_SUMMARY every N scan cycles (0 disables summary).
PERF_SUMMARY_EVERY_CYCLES: int = _get_int_env("PERF_SUMMARY_EVERY_CYCLES", 20)


# --- Data readiness gate (cache coverage) ---

# Minimum trend timeframe bars required before the engine is likely to work.
MIN_TREND_BARS: int = _get_int_env("MIN_TREND_BARS", 55)

# Minimum entry timeframe bars required before running entry detectors.
MIN_ENTRY_BARS: int = _get_int_env("MIN_ENTRY_BARS", 200)

# In NOTIFY_MODE=admin_only, rate-limit data_gap notifications per symbol.
DATA_GAP_NOTIFY_COOLDOWN_MIN: int = _get_int_env("DATA_GAP_NOTIFY_COOLDOWN_MIN", 60)

# Rate-limit DATA_GAP logs per (symbol,tf) to once per N seconds.
DATA_GAP_LOG_INTERVAL_SEC: int = _get_int_env("DATA_GAP_LOG_INTERVAL_SEC", 3600)


# --- Trend / regime handling ---

# If True: require a clear structure trend before allowing any signal.
# If False (default): when structure trend is unclear, allow range-safe detectors
# (e.g., SR bounce / fakeout / range box) with a small score penalty.
REQUIRE_CLEAR_TREND_FOR_SIGNAL: bool = _get_bool_env("REQUIRE_CLEAR_TREND_FOR_SIGNAL", False)
