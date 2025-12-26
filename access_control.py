# access_control.py
"""
Telegram ботын access control:
- Админ хэрэглэгч (config.ADMIN_USER_ID)
- allowed_users.json (preferred) эсвэл allowed_users.txt файлд бусад зөвшөөрөгдсөн хэрэглэгчид
"""

from __future__ import annotations
import os
from typing import Set
import json
from pathlib import Path

from config import ADMIN_USER_ID

from core.atomic_io import atomic_write_text

ALLOWED_USERS_JSON = "allowed_users.json"
ALLOWED_USERS_TXT = "allowed_users.txt"

_ALLOWED_USERS: Set[int] = set()


def load_allowed_users() -> None:
    """allowed users жагсаалтыг ачаална.

    Priority:
    1) allowed_users.json (list[int] эсвэл {"allowed": [..]})
    2) allowed_users.txt (one id per line)
    """
    global _ALLOWED_USERS
    _ALLOWED_USERS = set()

    # 1) JSON
    if os.path.exists(ALLOWED_USERS_JSON):
        try:
            with open(ALLOWED_USERS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                candidates = data
            elif isinstance(data, dict) and isinstance(data.get("allowed"), list):
                candidates = data.get("allowed")
            else:
                candidates = []
            for item in candidates:
                try:
                    _ALLOWED_USERS.add(int(item))
                except Exception:
                    continue
            return
        except Exception:
            _ALLOWED_USERS = set()
            # fall through to TXT

    try:
        if not os.path.exists(ALLOWED_USERS_TXT):
            return
        with open(ALLOWED_USERS_TXT, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    _ALLOWED_USERS.add(int(line))
                except ValueError:
                    continue
    except Exception:
        # Алдаа гарсан ч бот зогсохгүй, зүгээр л хоосон листтэй явна
        _ALLOWED_USERS = set()


def _save_allowed_users() -> None:
    try:
        # Save as JSON (preferred)
        atomic_write_text(
            Path(ALLOWED_USERS_JSON),
            json.dumps(sorted(_ALLOWED_USERS), ensure_ascii=False, indent=2),
        )
    except Exception:
        # Файл бичиж чадахгүй бол чимээгүй алгасна
        pass


def get_admin_id() -> int:
    return ADMIN_USER_ID


def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID != 0 and user_id == ADMIN_USER_ID


def is_allowed(user_id: int) -> bool:
    """Админ байвал шууд зөвшөөрнө, бусад нь allowed_users жагсаалтад байх ёстой."""
    if is_admin(user_id):
        return True
    return user_id in _ALLOWED_USERS


def add_allowed_user(user_id: int) -> None:
    """Админ хэрэглэх 'Зөвшөөрөх 123456' командаар хэрэглэгч нэмнэ."""
    global _ALLOWED_USERS
    _ALLOWED_USERS.add(user_id)
    _save_allowed_users()
