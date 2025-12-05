# access_control.py
"""
Telegram ботын access control:
- Админ хэрэглэгч (config.ADMIN_USER_ID)
- allowed_users.txt файлд бусад зөвшөөрөгдсөн хэрэглэгчид
"""

from __future__ import annotations
import os
from typing import Set
from config import ADMIN_USER_ID

ALLOWED_USERS_FILE = "allowed_users.txt"

_ALLOWED_USERS: Set[int] = set()


def load_allowed_users() -> None:
    """allowed_users.txt файлд байгаа бүх ID-г ачаална."""
    global _ALLOWED_USERS
    _ALLOWED_USERS = set()
    if not os.path.exists(ALLOWED_USERS_FILE):
        # Файл байхгүй бол зөвхөн админ эрхтэй
        return

    try:
        with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
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
        with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as f:
            for uid in sorted(_ALLOWED_USERS):
                f.write(str(uid) + "\n")
    except Exception:
        # Файл бичиж чадахгүй бол чимээгүй алгасна
        pass


def get_admin_id() -> int:
    return ADMIN_USER_ID


def is_admin(user_id: int) -> bool:
    return ADMIN_USER_ID != 0 and user_id == ADMIN_USER_ID


def is_allowed(user_id: int) -> bool:
    """Админ байвал шууд зөвшөөрнө, бусад нь allowed_users.txt-д байх ёстой."""
    if is_admin(user_id):
        return True
    return user_id in _ALLOWED_USERS


def add_allowed_user(user_id: int) -> None:
    """Админ хэрэглэх 'Зөвшөөрөх 123456' командаар хэрэглэгч нэмнэ."""
    global _ALLOWED_USERS
    _ALLOWED_USERS.add(user_id)
    _save_allowed_users()
