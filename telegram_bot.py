import os
import traceback

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from ig_client import IGClient
from strategy import analyze_xauusd_full
from ai_explainer import explain_signal_ganbayar


EPIC_XAUUSD = "CS.D.CFDGOLD.BMU.IP"  # Spot Gold ($1) EPIC


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /start команд – товч танилцуулга """
    text = (
        "Сайн уу, би Ганбаярын multi-TF анализатор бот 🤖\n\n"
        "/xau – XAUUSD (Spot Gold) дээр чиний стратегиар анализ хийнэ.\n"
        "D1 + H4 + H1 + M15 + Fib + R:R ≥ 1:3 логик ажиллана."
    )
    await update.message.reply_text(text)


def _run_analysis() -> dict:
    """
    IG + strategy-г дуудаад нэг удаагийн анализ хийдэг туслах функц.
    Telegram handler дотор ашиглана.
    """
    ig = IGClient.from_env(is_demo=False)

    d1_candles = ig.get_candles(EPIC_XAUUSD, resolution="DAY", max_points=200)
    h4_candles = ig.get_candles(EPIC_XAUUSD, resolution="HOUR_4", max_points=200)
    h1_candles = ig.get_candles(EPIC_XAUUSD, resolution="HOUR", max_points=200)
    m15_candles = ig.get_candles(EPIC_XAUUSD, resolution="MINUTE_15", max_points=200)

    decision = analyze_xauusd_full(d1_candles, h4_candles, h1_candles, m15_candles)
    return decision


def _format_decision_text(decision: dict) -> str:
    """Strategy-гийн decision dict-ийг Telegram-д харахад гоё текст болгоно."""
    status = decision.get("status")
    d1_trend = decision.get("d1_trend")
    h4_trend = decision.get("h4_trend")
    d1_levels = decision.get("d1_levels")
    h4_levels = decision.get("h4_levels")
    fib_zone = decision.get("fib_zone")

    header = "📊 *Ганбаярын XAUUSD анализ (v2)*\n"
    tf_part = (
        f"🕒 D1 trend: *{d1_trend}*\n"
        f"🕒 H4 trend: *{h4_trend}*\n"
        f"D1 levels: `{d1_levels}`\n"
        f"H4 levels: `{h4_levels}`\n"
    )
    if fib_zone:
        tf_part += f"Fib 0.5–0.618 zone (H4): `{fib_zone}`\n"

    if status == "no_data":
        return header + tf_part + "\n❌ Өгөгдөл дутуу байна.\n" + decision.get("reason", "")

    if status == "no_trade":
        return header + tf_part + "\nℹ *NO TRADE* – " + decision.get("reason", "")

    if status == "no_trade_rr":
        dir_ = decision.get("direction")
        entry = decision.get("entry")
        sl = decision.get("sl")
        tps = decision.get("tp_candidates")
        body = (
            f"\nDirection: *{dir_}*\n"
            f"Entry: `{entry}`\n"
            f"SL: `{sl}`\n"
            f"TP candidates: `{tps}`\n"
            "\n❌ R:R ≥ 1:3 хангах TP олдсонгүй. *NO TRADE*."
        )
        return header + tf_part + body

    if status == "trade":
        dir_ = decision["direction"]
        entry = decision["entry"]
        sl = decision["sl"]
        tp = decision["tp"]
        rr = decision["rr"]
        tps = decision.get("tp_candidates")

        body = (
            f"\n✅ *TRADE SETUP ОЛДЛОО* \n"
            f"Direction: *{dir_}*\n"
            f"Entry: `{entry}`\n"
            f"SL: `{sl}`\n"
            f"TP candidates: `{tps}`\n"
            f"Сонгосон TP: `{tp}`\n"
            f"R:R ≈ *1:{rr:.2f}*\n"
        )
        return header + tf_part + body

    # safety fallback
    return header + tf_part + "\n⚠ Тодорхойгүй статус: `" + str(status) + "`"


async def xau(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /xau команд – IG + strategy + GPT тайлбар гүйцэтгэнэ. """
    await update.message.reply_text("⏳ XAUUSD дээр анализ хийж байна, хүлээгээрэй...")

    try:
        decision = _run_analysis()
        status = decision.get("status")

        text = _format_decision_text(decision)

        # Эхний текст – хүний нүдэнд ойлгомжтой анализ
        await update.message.reply_markdown(text)

        # Хэрэв бодит trade setup байвал GPT-ийн тайлбар бас нэмье
        if status == "trade":
            signal = {
                "pair": "XAUUSD",
                "direction": decision["direction"],
                "timeframe": decision.get("entry_tf", "M15"),
                "entry": decision["entry"],
                "sl": decision["sl"],
                "tp": decision["tp"],
                "rr": decision["rr"],
                "context": {
                    "d1_trend": decision.get("d1_trend"),
                    "d1_levels": decision.get("d1_levels"),
                    "h4_trend": decision.get("h4_trend"),
                    "h4_levels": decision.get("h4_levels"),
                    "fib_zone": decision.get("fib_zone"),
                },
            }

            try:
                explanation = explain_signal_ganbayar(signal)
                await update.message.reply_text(
                    "🧠 Ганбаярын арга барилаар тайлбар:\n\n" + explanation
                )
            except Exception as e:
                await update.message.reply_text(
                    "⚠ GPT тайлбар авах үед алдаа гарлаа: " + str(e)
                )

    except Exception as e:
        traceback.print_exc()
        await update.message.reply_text(f"⚠ Алдаа гарлаа: {e}")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env хувьсагч олдсонгүй!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("xau", xau))

    print("Telegram бот аслаа. CTRL+C дарж зогсооно.")
    app.run_polling()


if __name__ == "__main__":
    main()
