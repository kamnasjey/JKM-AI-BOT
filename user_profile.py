# user_profile.py
"""
Хэрэглэгч бүрийн 'Миний стратеги' профайлыг файл дээр хадгалах simple систем.

Одоогийн хувилбар:
  - STR: ... гэж бичихэд тухайн текстийг "note" болгон хадгална
  - min_rr, trend_tf, entry_tf зэрэгт default утга тавина
  - Дараа нь user_core_engine шиг илүү advanced engine нэмэх суурь болно.

Файл: user_profiles.json
"""

from __future__ import annotations
import json
import os
from typing import Dict, Any

PROFILES_FILE = "user_profiles.json"

DEFAULT_PROFILE: Dict[str, Any] = {
    "name": "Ganbayar default strategy",
    "style": "trend-following / swing",
    "note": "Default профайл. H4 дээр чиглэл, M15 дээр entry, RR≥1:3.",
    "min_rr": 3.0,
    "risk_percent": 1.0,
    "trend_tf": "H4",
    "entry_tf": "M15",
}


def _load_all_profiles() -> Dict[str, Any]:
    if not os.path.exists(PROFILES_FILE):
        return {}
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_all_profiles(data: Dict[str, Any]) -> None:
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_profile(user_id: int) -> Dict[str, Any]:
    all_profiles = _load_all_profiles()
    key = str(user_id)
    if key not in all_profiles:
        all_profiles[key] = DEFAULT_PROFILE.copy()
        _save_all_profiles(all_profiles)
    return all_profiles.get(key, DEFAULT_PROFILE.copy())


def set_profile_from_text(user_id: int, text: str) -> str:
    """
    STR: ... маягийн текстийг аваад,
    одоохондоо зүгээр л note талбарт хадгална, RR, TF-г default хэвээр үлдээнэ.
    Ирээдүйд OpenAI ашиглан JSON parse хийж advanced болгоно.
    """
    content = text.strip()
    if content.lower().startswith("str:"):
        content = content[4:].strip()

    all_profiles = _load_all_profiles()
    key = str(user_id)
    base = all_profiles.get(key, DEFAULT_PROFILE.copy())

    base["note"] = content
    all_profiles[key] = base
    _save_all_profiles(all_profiles)

    return "✅ Стратегийн тайлбарыг хадгаллаа."


def format_profile_for_user(user_id: int) -> str:
    p = get_profile(user_id)
    return (
        "<b>Миний стратегийн профайл</b>\n"
        f"Нэр: {p.get('name')}\n"
        f"Стиль: {p.get('style')}\n"
        f"Хамгийн бага RR: 1:{p.get('min_rr')}\n"
        f"Нэг арилжаанд эрсдэл: ~{p.get('risk_percent')}%\n"
        f"Үндсэн timeframe-үүд: {p.get('trend_tf')}, {p.get('entry_tf')}\n"
        f"Тэмдэглэл: {p.get('note')}"
    )
