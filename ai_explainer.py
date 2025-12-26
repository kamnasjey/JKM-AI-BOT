# ai_explainer.py

import os
import json
from openai import OpenAI

# API key-гээ энд шууд бичихгүй, түр туршилтаар бичиж болно,
# жинхэнэ үед нь os.environ-оос уншаарай.
API_KEY = os.getenv("OPENAI_API_KEY", "")

client = OpenAI(api_key=API_KEY)


def explain_signal_ganbayar(signal: dict) -> str:
    """
    Signal dict-ээ аваад (pair, entry, sl, tp, rr, context...),
    Ганбаярын арга барилын дагуу монголоор тайлбар бичүүлнэ.
    """

    pair = signal["pair"]
    direction = signal["direction"]
    timeframe = signal["timeframe"]
    entry = signal["entry"]
    sl = signal["sl"]
    tp = signal["tp"]
    rr = signal["rr"]
    ctx = signal.get("context", {})

    h1_trend = ctx.get("h1_trend")
    h1_levels = ctx.get("h1_levels")

    # GPT-д өгөх prompt-оо бэлдье
    user_content = f"""
Чи форекс арилжаа хийдэг Ганбаяр гэдэг трейдэрийн дотор тархи шиг ажилла.
Түүний үндсэн философи:
- Price action + multi-timeframe анализ (том TF-ээр чиглэл, жижиг TF-ээр entry).
- Хамгийн багадаа R:R 1:3 байх ёстой, quality сетапыг л авдаг.
- Stop loss-гүй ордоггүй.
- Зүгээр random scalp хийдэггүй, level + candle давхцлыг хүлээдэг.

Дараах сигналийн мэдээлэл байна:

Хос: {pair}
Чиглэл: {direction}
Entry: {entry}
SL: {sl}
TP: {tp}
R:R: {rr:.2f}
Timeframe (entry): {timeframe}

H1 тренд: {h1_trend}
H1 түвшинүүд: {h1_levels}

Дээрх мэдээлэлд үндэслээд:
1) Энэ сетапыг яагаад ер нь авч болохоор гэж үзэж байгааг тайлбарла.
2) Ямар гол давхцал (trend, level, candle structure) байна гэж харж байгааг хэл.
3) Ямар эрсдэл, юу буруу болох эрсдэлтэй вэ гэдгийг дурд.
4) Сэтгэл хөдлөлөөс хамаараад шууд үсрэх биш, ямар нөхцөлд авч, ямар нөхцөлд алгасахыг тодорхой хэл.

Хэлний стиль:
- Монгол хэлээр, ойлгомжтой, илүү "ахын" зөвлөгөө өгч байгаа мэт
- Чимэг үг бага, гол нь логик, тайлбар тодорхой байг.
"""

    resp = client.chat.completions.create(
        model="gpt-4.1-mini",  # эсвэл gpt-4.1, gpt-5.1 гэх мэт
        messages=[
            {"role": "system", "content": "Чи монгол хэлээр ярьдаг форекс трейдинг зөвлөх."},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
    )

    return resp.choices[0].message.content.strip()
