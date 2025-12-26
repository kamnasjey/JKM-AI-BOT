import logging
import json
import httpx
from typing import Dict, Any, Optional, Union, List
import io
import os
from datetime import datetime, timedelta
from config import TELEGRAM_TOKEN, DEFAULT_CHAT_ID
from services.models import SignalEvent
from notify.formatters import format_signal_message

logger = logging.getLogger("notifier.telegram")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Deduplication Config
DEDUP_WINDOW_MINUTES = 30
PRICE_TOLERANCE_PERCENT = 0.001  # 0.1% difference considered "same setup"

class TelegramNotifier:
    def __init__(self, token: str = TELEGRAM_TOKEN, default_chat_id: int = DEFAULT_CHAT_ID):
        self.token = token
        self.default_chat_id = default_chat_id
        if not self.token:
            logger.warning("TELEGRAM_TOKEN is missing. Notification will fail.")
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        
        # History: list of (SignalEvent, sent_time)
        self._sent_history: List[SignalEvent] = []

    def _is_duplicate(self, signal: SignalEvent) -> bool:
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=DEDUP_WINDOW_MINUTES)
        
        # Clean old history
        self._sent_history = [s for s in self._sent_history if s.generated_at > cutoff]
        
        for past_sig in self._sent_history:
            if past_sig.pair != signal.pair:
                continue
            if past_sig.direction != signal.direction:
                continue
            if past_sig.timeframe != signal.timeframe:
                continue
                
            # Check entry price proximity
            if abs(past_sig.entry - signal.entry) / past_sig.entry < PRICE_TOLERANCE_PERCENT:
                # It's effectively the same signal
                return True
                
        return False


    def send_signal(
        self,
        signal: SignalEvent,
        chart_img: Optional[io.BytesIO] = None,
        *,
        chat_id: Optional[Union[int, str]] = None,
        explain: Optional[Dict[str, Any]] = None,
        mode: str = "all",
    ) -> bool:
        """
        Smart send: checks dedup before sending.
        """
        if self._is_duplicate(signal):
            logger.info(f"Signal suppressed (Duplicate/Cooldown): {signal.pair} {signal.direction}")
            return False
            
        # Prefer ExplainPayload formatting (stable and NA-safe)
        caption = None
        try:
            if isinstance(explain, dict) and explain:
                caption = format_signal_message(explain, mode=mode)
        except Exception:
            caption = None

        # Fallback formatting (legacy)
        if not caption:
            icon = "🟢" if signal.direction == "BUY" else "🔴"
            dir_mn = "ӨСӨХ (BUY)" if signal.direction == "BUY" else "УНАХ (SELL)"

            # Translate typical reasons if possible
            reasons_formatted = []
            for r in signal.reasons:
                if "Uptrend" in r:
                    r = r.replace("Uptrend", "Өсөх тренд")
                if "Downtrend" in r:
                    r = r.replace("Downtrend", "Унах тренд")
                if "Align" in r:
                    r = "D1 болон H4 тренд баталгаажсан"
                reasons_formatted.append(f"✅ {r}")

            reasons_str = "\n".join(reasons_formatted)

            tz_h = int(getattr(signal, "tz_offset_hours", 0) or 0)
            local_dt = signal.generated_at + timedelta(hours=tz_h)
            local_stamp = local_dt.strftime("%Y-%m-%d %H:%M")

            engine_v = str(getattr(signal, "engine_version", "") or "").strip()
            engine_line = f"🧠 <b>Engine:</b> {engine_v}\n" if engine_v else ""

            caption = (
                f"⚡ <b>{signal.pair}</b> – {dir_mn} {icon}\n"
                f"--------------------------------\n"
                f"🎯 <b>Entry:</b> {signal.entry}\n"
                f"🛑 <b>SL:</b> {signal.sl}\n"
                f"💵 <b>TP:</b> {signal.tp}\n"
                f"⚖️ <b>RR:</b> {signal.rr:.2f}\n"
                f"⏱ <b>TF:</b> {signal.timeframe}\n\n"
                f"{engine_line}"
                f"🕒 <b>Time:</b> {local_stamp} (UTC{tz_h:+d})\n\n"
                f"📝 <b>Шалтгаан:</b>\n{reasons_str}\n\n"
                f"<i>#JKM_Bot_v1 #Signal</i>"
            )

        success = False
        if chart_img:
            success = self.send_photo(caption, chart_img, chat_id=chat_id)
        else:
            success = self.send_message(caption, chat_id=chat_id)
            
        if success:
            self._sent_history.append(signal)
            
        return success

    def send_message(
        self,
        text: str,
        chat_id: Optional[Union[int, str]] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML"
    ) -> bool:
        """
        Send a text message to Telegram.
        """
        target_chat_id = chat_id or self.default_chat_id
        if not target_chat_id:
            logger.warning("No chat_id provided for Telegram message.")
            return False

        payload: Dict[str, Any] = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(f"{self.api_url}/sendMessage", data=payload)
                resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_photo(
        self,
        caption: str,
        image_bytes: io.BytesIO,
        chat_id: Optional[Union[int, str]] = None,
        filename: str = "chart.png",
        parse_mode: str = "HTML"
    ) -> bool:
        """
        Send a photo (chart) to Telegram.
        """
        target_chat_id = chat_id or self.default_chat_id
        if not target_chat_id:
            logger.warning("No chat_id provided for Telegram photo.")
            return False

        # Ensure we are at the start of the bytes
        image_bytes.seek(0)
        
        files = {"photo": (filename, image_bytes.read())} # httpx needs bytes not IO
        
        # Reset again just in case replays happen, though read() consumes.
        # Actually httpx handles read() but let's be safe if passing stream, 
        # but here we pass bytes content directly.
        
        data: Dict[str, Any] = {
            "chat_id": target_chat_id,
            "caption": caption,
            "parse_mode": parse_mode,
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(f"{self.api_url}/sendPhoto", data=data, files=files)
                resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram photo: {e}")
            return False

# Global instance for easy import
telegram_notifier = TelegramNotifier()
