# config.py
"""
Энд бүх гол тохиргоонууд байна:
- Telegram токен
- Admin user ID
- Ажиглах хосууд, timeframe, авто scan интервал
"""

# --- Telegram ---
# config.py
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DEFAULT_CHAT_ID = 0


# Админ хэрэглэгчийн Telegram user ID
ADMIN_USER_ID = 1445509840  # Чиний ID


# --- Арилжааны тохиргоо ---

# IG дээрээ ашиглах хосууд
WATCH_PAIRS = [
    "XAUUSD",
    "EURJPY",
    "GBPJPY",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "EURUSD",
]

# Авто скан хийх timeframe (M5 дээр 5 минут тутам)
AUTO_TIMEFRAME = "M5"

# Гар аргаар 'Pair хайх' дээр ашиглах timeframe
MANUAL_TIMEFRAME = "M15"

# Авто скан давтамж (минут)
AUTO_SCAN_INTERVAL_MIN = 5

# Авто скан хийхэд ашиглах moving average-ийн хугацаа
AUTO_MA_PERIOD = 50
