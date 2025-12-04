import os
import logging
from typing import Dict

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from ig_client import IGClient
from analyzer import analyze_pair_multi_tf_ig_v2

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Чиний ашиглах pair -> env нэрийн map
PAIR_TO_EPIC_ENV: Dict[str, str] = {
    "XAUUSD": "EPIC_XAUUSD",
    "EURUSD": "EPIC_EURUSD",
    "EURJPY": "EPIC_EURJPY",
    "EURGBP": "EPIC_EURGBP",
    "GBPJPY": "EPIC_GBPJPY",
    "USDJPY": "EPIC_USDJPY",
}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Сайн байна уу, би JKM Trading AI бот 👋\n\n"
        "📌 Ашиглах командыг жишээтэй нь бичвэл:\n"
        "  /analyze XAUUSD\n"
        "  /analyze EURUSD\n"
        "  /analyze EURJPY\n"
        "  /analyze EURGBP\n"
        "  /analyze GBPJPY\n"
        "  /analyze USDJPY\n\n"
        "Чи коммандоо бичээд enter дарахад Ганбаярын мультитаймфрэйм "
        "арга барилаар анализ хийгээд буцааж өгнө."
    )
    await update.message.reply_text(text)


def _get_epic_for_pair(pair: str) -> str:
    """PAIR-аас env доторх EPIC утгыг уншина."""
    pair = pair.upper()
    env_name = PAIR_TO_EPIC_ENV.get(pair)
    if not env_name:
        raise ValueError(f"{pair} pair одоогоор дэмжигдэхгүй байна.")
    epic = os.getenv(env_name)
    if not epic:
        raise RuntimeError(
            f"{pair} EPIC тохируулаагүй байна. Серверийн env дээр {env_name} нэмэх хэрэгтэй."
        )
    return epic


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    # 1) PAIR авна
    if not context.args:
        await message.reply_text(
            "❗ Ашиглах хэлбэр:\n"
            "/analyze XAUUSD\n"
            "/analyze EURUSD\n"
            "/analyze EURJPY\n"
            "/analyze EURGBP\n"
            "/analyze GBPJPY\n"
            "/analyze USDJPY"
        )
        return

    pair = context.args[0].upper()
    await message.reply_text(f"⏳ {pair} дээр анализ хийж байна, жаахан хүлээгээрэй...")

    try:
        # 2) EPIC олж авна
        epic = _get_epic_for_pair(pair)

        # 3) IGClient-ээ нээж, анализ хийнэ
        ig = IGClient.from_env(is_demo=False)

        # analyzer.py доторх олон таймфрэймийн функц
        result = analyze_pair_multi_tf_ig_v2(ig, epic, pair)

        # 4) result-ийг текст болгоно
        #   - Хэрэв analyzer нь string буцаадаг бол шууд
        #   - dict байвал боломжийнээр форматлаж гаргана
        if isinstance(result, str):
            text = result
        elif isinstance(result, dict):
            # Хэрэв 'text' гэж түлхүүр байвал тэрийг ашиглая
            if "text" in result:
                text = result["text"]
            elif "summary" in result:
                text = result["summary"]
            else:
                # Фоллбэк: dict-ийг энгийн мөр болгож хэвлэх
                lines = []
                for k, v in result.items():
                    lines.append(f"{k}: {v}")
                text = "\n".join(lines)
        else:
            text = (
                f"{pair} анализын үр дүнг ойлгож чадсангүй. "
                "analyzer-ийн буцааж буй төрөл рүү нэг харъя."
            )

        # 5) Хариуг Telegram руу буцаана
        await message.reply_text(text)

    except Exception as e:
        logger.exception("Analyze команд дээр алдаа гарлаа")
        await message.reply_text(f"❌ Алдаа гарлаа: {e}")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env хувьсагч алга байна.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("analyze", analyze_command))

    logger.info("JKM Trading AI Telegram бот асаж байна...")
    app.run_polling()


if __name__ == "__main__":
    main()
