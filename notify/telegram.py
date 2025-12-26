from __future__ import annotations

from typing import Optional

import config
from services.notifier_telegram import telegram_notifier


def send_admin_alert(text: str) -> bool:
    """Send an admin-only alert message (never to normal users)."""
    chat_id: Optional[str] = None
    try:
        chat_id = getattr(config, "ADMIN_CHAT_ID", None) or getattr(config, "DEFAULT_CHAT_ID", None)
    except Exception:
        chat_id = None

    if not chat_id:
        return False

    try:
        return bool(telegram_notifier.send_message(str(text), chat_id=chat_id))
    except Exception:
        return False


def send_admin_recovery(text: str) -> bool:
    return send_admin_alert(text)


def send_admin_report(text: str) -> bool:
    return send_admin_alert(text)


def send_admin_coverage(text: str) -> bool:
    """Admin-only detector coverage report (alias of send_admin_report)."""
    return send_admin_report(text)
