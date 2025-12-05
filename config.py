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


# --- Арилжааны үндсэн тохиргоо ---

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
