from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from config import WEB_SESSION_TTL_MINUTES

_SESSION_STORE: Dict[str, Dict[str, Any]] = {}


def _now() -> datetime:
    return datetime.utcnow()


def _cleanup_expired_sessions() -> None:
    if not _SESSION_STORE:
        return
    now = _now()
    expired = [token for token, data in _SESSION_STORE.items() if data["expires_at"] <= now]
    for token in expired:
        _SESSION_STORE.pop(token, None)


def create_session(user_id: str) -> str:
    """Create a short-lived session token for web auth."""
    _cleanup_expired_sessions()
    token = secrets.token_urlsafe(32)
    _SESSION_STORE[token] = {
        "user_id": str(user_id),
        "expires_at": _now() + timedelta(minutes=WEB_SESSION_TTL_MINUTES),
    }
    return token


def get_user_id_for_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    session = _SESSION_STORE.get(token)
    if not session:
        return None
    if session["expires_at"] <= _now():
        _SESSION_STORE.pop(token, None)
        return None
    return session["user_id"]


def invalidate_session(token: str) -> None:
    if not token:
        return
    _SESSION_STORE.pop(token, None)


def refresh_session(token: str) -> None:
    """Extend a session's life if it is still valid."""
    if token not in _SESSION_STORE:
        return
    _SESSION_STORE[token]["expires_at"] = _now() + timedelta(
        minutes=WEB_SESSION_TTL_MINUTES
    )
