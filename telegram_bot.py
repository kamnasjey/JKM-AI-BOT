# telegram_bot.py
import logging
import time
import io
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle

from config import (
    TELEGRAM_TOKEN,
    DEFAULT_CHAT_ID,
    WATCH_PAIRS,
    AUTO_TIMEFRAME,
    MANUAL_TIMEFRAME,
    AUTO_SCAN_INTERVAL_MIN,
)
from access_control import (
    load_allowed_users,
    is_admin,
    is_allowed,
    add_allowed_user,
    get_admin_id,
)
from strategy import scan_pairs
from analyzer import analyze_pair_multi_tf_ig_v2
from ig_client import IGClient
from market_overview import get_market_overview_text
from user_profile import get_profile, set_profile_from_text, format_profile_for_user

import os

# ---------- Logging / Globals ----------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("jkm-trading-bot")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

LAST_SCAN_TIME: Optional[datetime] = None
LAST_MANUAL_SCAN_TIME: Optional[datetime] = None

_IG_CLIENT: Optional[IGClient] = None


def get_ig_client() -> IGClient:
    global _IG_CLIENT
    if _IG_CLIENT is not None:
        return _IG_CLIENT
    is_demo_env = os.getenv("IG_IS_DEMO", "false").lower() in ("1", "true", "yes")
    _IG_CLIENT = IGClient.from_env(is_demo=is_demo_env)
    return _IG_CLIENT


def get_epic_for_pair(pair: str) -> Optional[str]:
    key = f"EPIC_{pair.replace('/', '')}"
    epic = os.getenv(key, "").strip()
    return epic or None


def tf_to_ig_resolution(tf: str) -> str:
    tf = (tf or "").upper().replace(" ", "")
    mapping = {
        "M1": "MINUTE",
        "M5": "MINUTE_5",
        "M15": "MINUTE_15",
        "M30": "MINUTE_30",
        "H1": "HOUR",
        "H4": "HOUR_4",
        "D1": "DAY",
    }
    return mapping.get(tf, "MINUTE_15")


def load_ig_candles_for_chart(pair: str, timeframe: str, limit: int = 300) -> List[Dict[str, Any]]:
    ig = get_ig_client()
    epic = get_epic_for_pair(pair)
    if not epic:
        raise RuntimeError(f"EPIC_{pair} env тохируулагдаагүй байна.")

    res = tf_to_ig_resolution(timeframe)
    raw = ig.get_candles(epic, resolution=res, max_points=limit)

    candles: List[Dict[str, Any]] = []
    for c in raw[-limit:]:
        t_str = c["time"]
        try:
            dt = datetime.fromisoformat(t_str.replace("Z", ""))
        except Exception:
            dt = datetime.utcnow()
        candles.append(
            {
                "time": dt,
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
            }
        )
    return candles


# ---------- Telegram helpers ----------

def send_telegram_message(
    text: str,
    chat_id: Optional[int] = None,
    reply_markup: Optional[Dict[str, Any]] = None,
) -> None:
    if chat_id is None or chat_id == 0:
        chat_id = DEFAULT_CHAT_ID

    if not chat_id:
        logger.warning("chat_id тодорхойгүй байна, мессеж илгээгээгүй.")
        return

    url = f"{TELEGRAM_API_URL}/sendMessage"
    data: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup is not None:
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    try:
        resp = httpx.post(url, data=data, timeout=20)
        resp.raise_for_status()
        logger.info("Telegram-д текст мессеж илгээлээ")
    except Exception as e:
        logger.error(f"Telegram text илгээхэд алдаа: {e}")


def send_telegram_photo(
    caption: str,
    image_bytes_io: io.BytesIO,
    chat_id: Optional[int] = None,
) -> None:
    if chat_id is None or chat_id == 0:
        chat_id = DEFAULT_CHAT_ID

    if not chat_id:
        logger.warning("chat_id тодорхойгүй байна, зураг илгээгээгүй.")
        return

    url = f"{TELEGRAM_API_URL}/sendPhoto"
    files = {"photo": ("chart.png", image_bytes_io, "image/png")}
    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML",
    }

    try:
        resp = httpx.post(url, data=data, files=files, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Telegram зураг илгээхэд алдаа: {e}")


def get_main_keyboard() -> Dict[str, Any]:
    return {
        "keyboard": [
            ["Эхлэх", "Зах зээлийн тойм"],
            ["Төлөв", "Хослолууд"],
            ["Pair хайх", "Миний стратеги"],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def get_request_access_keyboard() -> Dict[str, Any]:
    return {
        "keyboard": [["Эрх хүсэх"]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def get_pairs_inline_keyboard() -> Dict[str, Any]:
    rows = []
    for pair in WATCH_PAIRS:
        rows.append(
            [
                {
                    "text": format_pair_display(pair),
                    "callback_data": f"scan_pair:{pair}",
                }
            ]
        )
    return {"inline_keyboard": rows}


# ---------- Chart + text ----------

def format_pair_display(pair: str) -> str:
    if len(pair) == 6:
        return f"{pair[:3]}/{pair[3:]}"
    return pair


def generate_chart_image(
    candles: List[Dict[str, Any]],
    pair_for_title: str,
    timeframe: str,
) -> io.BytesIO:
    """
    Candlestick chart – өсөлт ногоон, уналт улаан,
    TradingView-тай төстэй хар background-тай.
    """
    if not candles:
        return io.BytesIO()

    dates = [mdates.date2num(c["time"]) for c in candles]
    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    fig, ax = plt.subplots(figsize=(9, 4))

    # Dark theme
    bg_color = "#131722"
    grid_color = "#363c4e"
    text_color = "#d1d4dc"

    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    for spine in ax.spines.values():
        spine.set_color(grid_color)

    ax.tick_params(colors=text_color)
    ax.yaxis.label.set_color(text_color)
    ax.xaxis.label.set_color(text_color)

    if len(dates) > 1:
        width = (dates[-1] - dates[0]) / len(dates) * 0.6
    else:
        width = 0.0005

    for x, o, h, l, c in zip(dates, opens, highs, lows, closes):
        color = "#26a69a" if c >= o else "#ef5350"
        ax.vlines(x, l, h, color=color, linewidth=0.6)
        lower = min(o, c)
        height = abs(c - o)
        if height == 0:
            height = max((h - l) * 0.05, 0.0001)
        rect = Rectangle(
            (x - width / 2, lower),
            width,
            height,
            facecolor=color,
            edgecolor=color,
            linewidth=0.5,
        )
        ax.add_patch(rect)

    ax.set_xlim(min(dates) - width, max(dates) + width)
    ax.xaxis_date()
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M"))

    ax.set_title(f"{pair_for_title} – {timeframe}", color=text_color, fontsize=11)
    ax.set_xlabel("Time", color=text_color)
    ax.set_ylabel("Price", color=text_color)

    ax.grid(True, alpha=0.25, color=grid_color)

    buf = io.BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png", dpi=130)
    plt.close(fig)
    buf.seek(0)
    return buf


def _estimate_pips(pair: str, price_diff: float) -> float:
    diff = abs(price_diff)
    if pair.startswith("XAU"):
        pip = 0.1
    elif "JPY" in pair:
        pip = 0.01
    else:
        pip = 0.0001
    return diff / pip if pip != 0 else 0.0


def format_signal_text(pair: str, setup: Dict[str, Any], timeframe: str) -> str:
    pair_disp = format_pair_display(pair)
    direction = setup["direction"]
    entry = setup["entry"]
    sl = setup["sl"]
    tp = setup["tp"]
    ma = setup["ma"]

    sl_pips = _estimate_pips(pair, entry - sl)
    tp_pips = _estimate_pips(pair, tp - entry)
    rr = (tp_pips / sl_pips) if sl_pips > 0 else 0

    if direction == "BUY":
        bias_text = (
            "Үнэ 50 хугацааны дунджаас ДЭЭШ байрлаж байгаа тул "
            "богино хугацаанд өсөх хандлага давамгайлж байна."
        )
    else:
        bias_text = (
            "Үнэ 50 хугацааны дунджаас ДОРОО байрлаж байгаа тул "
            "богино хугацаанд унах хандлага давамгайлж байна."
        )

    if sl_pips > 0 and tp_pips > 0:
        risk_text = (
            f"SL ойролцоогоор {sl_pips:.1f} пип, "
            f"TP ойролцоогоор {tp_pips:.1f} пип зайтай, "
            f"эрсдэл/ашгийн харьцаа ~1:{rr:.1f} орчим байна."
        )
    else:
        risk_text = "SL/TP-ийн зайг ойролцоогоор тооцоолсон."

    return (
        f"📈 <b>JKM Trading Signal</b>\n"
        f"Хослол: <b>{pair_disp}</b>\n"
        f"Чиглэл: <b>{direction}</b>\n"
        f"Entry: <code>{entry}</code>\n"
        f"SL: <code>{sl}</code>\n"
        f"TP: <code>{tp}</code>\n"
        f"MA(50): <code>{ma}</code>\n"
        f"Timeframe: {timeframe}\n"
        f"Цаг: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
        f"📝 <b>Тайлбар</b>\n"
        f"{bias_text}\n"
        f"{risk_text}"
    )


def get_status_text() -> str:
    if LAST_SCAN_TIME is None:
        last_scan_str = "Одоогоор автомат скан хийгдээгүй."
    else:
        last_scan_str = LAST_SCAN_TIME.strftime("%Y-%m-%d %H:%M:%S (UTC)")

    pairs_str = ", ".join(format_pair_display(p) for p in WATCH_PAIRS)

    return (
        "<b>JKM-trading-bot төлөв</b>\n"
        f"⏱ Авто скан давтамж: <b>{AUTO_SCAN_INTERVAL_MIN} минут</b>\n"
        f"📊 Авто timeframe: <b>{AUTO_TIMEFRAME}</b>\n"
        f"💱 Идэвхтэй хослолууд: <b>{pairs_str}</b>\n"
        f"🕒 Сүүлд авто скан хийсэн: {last_scan_str}"
    )


def get_pairs_text() -> str:
    lines = "\n".join(f"• {format_pair_display(p)}" for p in WATCH_PAIRS)
    return (
        "<b>Идэвхтэй хослолууд</b>\n"
        f"{lines}\n\n"
        f"Авто скан timeframe: <b>{AUTO_TIMEFRAME}</b>\n"
        f"Доорх хослолын товч дээр дарж тухайн pair дээр ганцаар нь шинжилгээ хийлгэнэ."
    )


# ---------- Jobs ----------

def scan_job() -> None:
    """AUTO_TIMEFRAME дээрх автомат scan – limit=300 bar."""
    global LAST_SCAN_TIME
    LAST_SCAN_TIME = datetime.utcnow()

    logger.info("==> АВТО SCAN эхэллээ")

    results = scan_pairs(
        timeframe=AUTO_TIMEFRAME,
        limit=300,
        pairs=WATCH_PAIRS,
    )

    if not results:
        logger.info("Авто scan – нэг ч setup олдсонгүй.")
        return

    for r in results:
        pair = r["pair"]
        tf = r["timeframe"]
        setup = r["setup"]
        candles = r["candles"]

        text = format_signal_text(pair, setup, tf)
        img_buf = generate_chart_image(candles, format_pair_display(pair), tf)
        send_telegram_photo(text, img_buf)


def manual_scan_pairs(chat_id: int) -> None:
    """'Pair хайх' – MANUAL_TIMEFRAME дээр бүх хосыг 300 bar-аар scan, 5 мин cooldown."""
    global LAST_MANUAL_SCAN_TIME
    now = datetime.utcnow()

    if LAST_MANUAL_SCAN_TIME is not None:
        diff = now - LAST_MANUAL_SCAN_TIME
        if diff < timedelta(minutes=5):
            remaining = timedelta(minutes=5) - diff
            mins = int(remaining.total_seconds() // 60)
            secs = int(remaining.total_seconds() % 60)
            send_telegram_message(
                f"⏳ Pair хайлт саяхан хийгдсэн байна.\n"
                f"{mins} минут {secs} секундийн дараа дахин хайж болно.",
                chat_id=chat_id,
            )
            return

    LAST_MANUAL_SCAN_TIME = now
    send_telegram_message(
        f"🔍 Бүх идэвхтэй хослолуудаас setup хайж байна ({MANUAL_TIMEFRAME})...",
        chat_id=chat_id,
    )

    results = scan_pairs(
        timeframe=MANUAL_TIMEFRAME,
        limit=300,
        pairs=WATCH_PAIRS,
    )

    if not results:
        send_telegram_message(
            "❌ Одоогоор ямар ч хослол дээр setup илрээгүй байна.",
            chat_id=chat_id,
        )
        return

    for r in results:
        pair = r["pair"]
        tf = r["timeframe"]
        setup = r["setup"]
        candles = r["candles"]

        text = format_signal_text(pair, setup, tf)
        img_buf = generate_chart_image(candles, format_pair_display(pair), tf)
        send_telegram_photo(text, img_buf, chat_id=chat_id)


def scan_single_pair(chat_id: int, pair: str, timeframe: Optional[str] = None) -> None:
    """
    Хослолууд дотроос ганц pair дээр дарсан үед:
      - Олон timeframe (D1, H4, H1, M15) анализ (text) ALWAYS
      - M15 chart ALWAYS
      - Setup байвал analyzer дотороо TRADE/NO TRADE гэж өөрөө тайлбарлана.
    """
    tf = timeframe or MANUAL_TIMEFRAME
    pair_disp = format_pair_display(pair)

    send_telegram_message(
        f"🔎 <b>{pair_disp}</b> дээр олон timeframe анализ хийж байна ({tf})...",
        chat_id=chat_id,
    )

    try:
        ig = get_ig_client()
        epic = get_epic_for_pair(pair)
        if not epic:
            send_telegram_message(
                f"⚠ <b>{pair_disp}</b> дээр EPIC тохируулагдаагүй байна. "
                f"Render / .env дээр EPIC_{pair.replace('/', '')} хувьсагчийг заавал тавина уу.",
                chat_id=chat_id,
            )
            return

        # 1) Олон timeframe текстэн анализ
        analysis_text = analyze_pair_multi_tf_ig_v2(ig, epic, pair_disp)

        # 2) M15 chart
        chart_tf = "M15"
        candles = load_ig_candles_for_chart(pair, chart_tf, limit=300)

        if not candles:
            send_telegram_message(analysis_text, chat_id=chat_id)
            return

        img_buf = generate_chart_image(candles, pair_disp, chart_tf)
        send_telegram_photo(analysis_text, img_buf, chat_id=chat_id)

    except Exception as e:
        logger.exception("scan_single_pair error:")
        send_telegram_message(
            f"⚠ <b>{pair_disp}</b> анализ хийхэд алдаа гарлаа:\n{e}",
            chat_id=chat_id,
        )


# ---------- Callback handler ----------

def handle_callback(callback: Dict[str, Any]) -> None:
    query_id = callback.get("id")
    data = callback.get("data", "") or ""
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    from_user = callback.get("from") or {}
    user_id = from_user.get("id")

    try:
        url = f"{TELEGRAM_API_URL}/answerCallbackQuery"
        httpx.post(url, data={"callback_query_id": query_id}, timeout=10)
    except Exception as e:
        logger.error(f"answerCallbackQuery алдаа: {e}")

    if chat_id is None or user_id is None:
        return

    if not is_allowed(user_id):
        send_telegram_message(
            "🔒 Энэ үйлдлийг хийхийн тулд эрх нээлгэх шаардлагатай.",
            chat_id=chat_id,
        )
        return

    if data.startswith("scan_pair:"):
        pair = data.split(":", 1)[1]
        scan_single_pair(chat_id, pair, timeframe=MANUAL_TIMEFRAME)


# ---------- Updates loop ----------

def handle_updates() -> None:
    logger.info("Telegram updates loop эхэллээ")

    url = f"{TELEGRAM_API_URL}/getUpdates"
    offset: Optional[int] = None

    while True:
        try:
            params: Dict[str, Any] = {"timeout": 20}
            if offset is not None:
                params["offset"] = offset

            resp = httpx.get(url, params=params, timeout=25)
            resp.raise_for_status()
            data = resp.json()

            for update in data.get("result", []):
                offset = update["update_id"] + 1

                callback = update.get("callback_query")
                if callback:
                    handle_callback(callback)
                    continue

                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue

                chat_id = message["chat"]["id"]
                user_id = chat_id  # private чат гэж үзэж байна
                text = (message.get("text") or "").strip()
                logger.info(f"Шинэ мессеж [{chat_id}]: {text}")

                lower_text = text.lower()

                # 1. Эрхгүй хэрэглэгч
                if not is_allowed(user_id):
                    if text == "Эрх хүсэх":
                        from_user = message.get("from", {})
                        first_name = from_user.get("first_name", "")
                        last_name = from_user.get("last_name", "")
                        admin_id = get_admin_id()

                        send_telegram_message(
                            f"🆕 <b>Шинэ эрх хүсэлт</b>\n"
                            f"User ID: <code>{user_id}</code>\n"
                            f"Нэр: {first_name} {last_name}",
                            chat_id=admin_id,
                        )
                        send_telegram_message(
                            "✅ Эрх хүсэлтийг админ руу илгээлээ.\n"
                            "Зөвшөөрсний дараа ботын бүх функцийг ашиглах боломжтой.",
                            chat_id=chat_id,
                            reply_markup=get_request_access_keyboard(),
                        )
                    else:
                        send_telegram_message(
                            "🔒 Энэ ботыг ашиглахын тулд эхлээд эрх нээлгэх шаардлагатай.\n\n"
                            "Доорх 'Эрх хүсэх' товчийг дарж админ руу хүсэлт илгээнэ үү.",
                            chat_id=chat_id,
                            reply_markup=get_request_access_keyboard(),
                        )
                    continue

                # 2. Админы 'Зөвшөөрөх 123456789'
                if is_admin(user_id) and lower_text.startswith("зөвшөөрөх"):
                    parts = text.split()
                    if len(parts) >= 2:
                        try:
                            target_id = int(parts[1])
                            add_allowed_user(target_id)
                            send_telegram_message(
                                f"✅ User ID {target_id} хэрэглэгчийн эрхийг нээлээ.",
                                chat_id=chat_id,
                            )
                            send_telegram_message(
                                "✅ Админ таны эрхийг нээлээ. Одоо ботын бүх функцийг ашиглаж болно.\n"
                                "Доорх 'Эхлэх' товчийг дарж эхлэнэ үү.",
                                chat_id=target_id,
                                reply_markup=get_main_keyboard(),
                            )
                        except Exception as e:
                            logger.error(f"Зөвшөөрөх команд алдаа: {e}")
                            send_telegram_message(
                                "❌ Зөвшөөрөх команд буруу. Жишээ: Зөвшөөрөх 123456789",
                                chat_id=chat_id,
                            )
                    else:
                        send_telegram_message(
                            "❌ Жишээ: Зөвшөөрөх 123456789",
                            chat_id=chat_id,
                        )
                    continue

                # 3. Үндсэн командууд

                # --- Миний стратеги харах ---
                if text == "Миний стратеги":
                    summary = format_profile_for_user(user_id)
                    send_telegram_message(
                        summary,
                        chat_id=chat_id,
                    )
                    continue

                # --- STR: ... ирвэл профайл шинэчлэх ---
                if lower_text.startswith("str:"):
                    msg = set_profile_from_text(user_id, text)
                    summary = format_profile_for_user(user_id)
                    send_telegram_message(
                        msg + "\n\n" + summary,
                        chat_id=chat_id,
                    )
                    continue

                if lower_text.startswith("/start") or text == "Эхлэх":
                    send_telegram_message(
                        "Сайн байна уу! 😊\n"
                        "Энэ бол <b>JKM-trading-bot</b>.\n\n"
                        "Бот зах зээлийг тогтмол хугацааны давтамжаар скан хийж,\n"
                        "setup илэрсэн үед график зурагтай дохио илгээнэ.\n\n"
                        "Доорх товчнуудаас сонгож ашиглана уу.",
                        chat_id=chat_id,
                        reply_markup=get_main_keyboard(),
                    )
                    continue

                if lower_text.startswith("/help") or lower_text.startswith("/tuslamj"):
                    send_telegram_message(
                        "<b>Товчнуудын тайлбар:</b>\n"
                        "• Эхлэх – Ботын тухай товч танилцуулга\n"
                        "• Зах зээлийн тойм – Макро, ерөнхий тайлбар (OpenAI ашиглах боломжтой)\n"
                        "• Төлөв – Ботын одоогийн төлөв, скан давтамж, хослолууд\n"
                        "• Хослолууд – Идэвхтэй хослолуудын жагсаалт\n"
                        "• Pair хайх – M15 дээрээс бүх хос дээр 300 bar-аар setup хайх (5 мин cooldown)\n"
                        "• Хослолын нэр дээр дарж ганцхан pair дээр олон timeframe анализ хийлгэж болно.\n",
                        chat_id=chat_id,
                        reply_markup=get_main_keyboard(),
                    )
                    continue

                if text == "Төлөв":
                    send_telegram_message(
                        get_status_text(),
                        chat_id=chat_id,
                    )
                    continue

                if text == "Хослолууд":
                    send_telegram_message(
                        get_pairs_text(),
                        chat_id=chat_id,
                        reply_markup=get_pairs_inline_keyboard(),
                    )
                    continue

                if text == "Pair хайх":
                    manual_scan_pairs(chat_id)
                    continue

                if text == "Зах зээлийн тойм":
                    send_telegram_message(
                        get_market_overview_text(),
                        chat_id=chat_id,
                    )
                    continue

                # Default
                send_telegram_message(
                    "Доорх товчнуудаас сонгож ашиглана уу.\n"
                    "Тусламж хэрэгтэй бол /tuslamj гэж бичиж болно.",
                    chat_id=chat_id,
                    reply_markup=get_main_keyboard(),
                )

        except Exception as e:
            logger.error(f"getUpdates алдаа: {e}")
            time.sleep(5)


# ---------- Main ----------

def main() -> None:
    logger.info("JKM-trading-bot эхэлж байна...")

    load_allowed_users()

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(scan_job, "interval", minutes=AUTO_SCAN_INTERVAL_MIN)
    scheduler.start()
    logger.info(f"АВТО SCAN {AUTO_SCAN_INTERVAL_MIN} минут тутам ажиллахаар тохирлоо")

    try:
        handle_updates()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt – bot унтарч байна...")
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
