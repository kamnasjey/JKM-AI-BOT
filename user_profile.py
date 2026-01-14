# user_profile.py
"""
Хэрэглэгч бүрийн 'Миний стратеги' профайлыг файл дээр хадгалах simple систем.

Одоогийн хувилбар:
  - STR: ... гэж бичихэд тухайн текстийг "note" болгон хадгална
  - min_rr, trend_tf, entry_tf зэрэгт default утга тавина
  - Дараа нь user_core_engine шиг илүү advanced engine нэмэх суурь болно.

Файл: user_profiles.json
"""


import re
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from user_db import (
    add_user,
    get_user,
    list_users,
    delete_user,
    get_account,
    get_last_str_update_at,
    set_last_str_update_at,
    get_last_str_update_day,
    set_last_str_update_day,
)
from services.models import UserProfile

from ai_strategy_builder import build_strategies_from_str_text

DEFAULT_PROFILE = UserProfile().model_dump()


def _parse_tz_offset_hours(raw: str) -> Optional[int]:
    """Parse timezone offset hours from text.

    Supported examples:
    - tz=8, tz=+8, tz=-5
    - timezone=+8
    - UTC+8, utc-5
    """
    m = re.search(r"\b(?:tz|timezone)\s*[:=]\s*([+-]?\d{1,2})\b", raw, re.IGNORECASE)
    if not m:
        m = re.search(r"\bUTC\s*([+-]\s*\d{1,2})\b", raw, re.IGNORECASE)
    if not m:
        return None
    try:
        val = int(str(m.group(1)).replace(" ", ""))
    except Exception:
        return None
    # Conservative bounds for common timezones
    if val < -12:
        val = -12
    if val > 14:
        val = 14
    return val


def _strip_tz_token(raw: str) -> str:
    # Remove tz=... or timezone=... or UTC+... tokens from a free-text STR note.
    s = re.sub(r"\b(?:tz|timezone)\s*[:=]\s*[+-]?\d{1,2}\b", "", raw, flags=re.IGNORECASE)
    s = re.sub(r"\bUTC\s*[+-]\s*\d{1,2}\b", "", s, flags=re.IGNORECASE)
    # Clean up extra whitespace
    return re.sub(r"\s{2,}", " ", s).strip()

def get_profile(user_id: int) -> Dict[str, Any]:
    user = get_user(str(user_id))
    if not user:
        # Create default
        prof = UserProfile(user_id=str(user_id))
        add_user(str(user_id), f"User {user_id}", prof.model_dump())
        return prof.model_dump()
    # Backfill timezone for older stored profiles
    if "tz_offset_hours" not in user or user.get("tz_offset_hours") is None:
        default_tz = int(os.getenv("DEFAULT_TZ_OFFSET_HOURS", "8") or "8")
        user["tz_offset_hours"] = default_tz
    return user

def parse_str_command(text: str) -> Dict[str, Any]:
    """
    Parses "STR: ..." text into a dictionary suitable for UserProfile update.
    Supports:
    - Loose key-value: "risk=1 trend=h4"
    - JSON block: "json={...}"
    - Natural language helpers: "exclude XAUUSD", "watch EURUSD"
    """
    updates: Dict[str, Any] = {}
    
    # Pre-cleaning
    raw = text
    if raw.lower().startswith("str:"):
        raw = raw[4:].strip()
    
    # 1. JSON Attempt
    # If user provided raw json
    json_match = re.search(r"\{.*\}", raw)
    if json_match:
        try:
            updates.update(json.loads(json_match.group(0)))
            return updates
        except:
            pass # Fallback to text parsing
            
    # 2. Regex Parsing for standard fields
    # Risk
    risk_match = re.search(r"(?:risk|risk_percent)\s*[:=]?\s*(\d+(\.\d+)?)", raw, re.IGNORECASE)
    if risk_match:
        updates["risk_percent"] = float(risk_match.group(1))

    # Min RR
    rr_match = re.search(r"(?:rr|min_rr)\s*[:=]?\s*(\d+(\.\d+)?)", raw, re.IGNORECASE)
    if rr_match:
        updates["min_rr"] = float(rr_match.group(1))

    # Timeframes - Trend
    trend_match = re.search(r"(?:trend|trend_tf)\s*[:=]?\s*([a-zA-Z0-9]+)", raw, re.IGNORECASE)
    if trend_match:
        updates["trend_tf"] = trend_match.group(1).upper()

    # Timeframes - Entry
    entry_match = re.search(r"(?:entry|entry_tf)\s*[:=]?\s*([a-zA-Z0-9]+)", raw, re.IGNORECASE)
    if entry_match:
        updates["entry_tf"] = entry_match.group(1).upper()

    # Require clear trend gate
    req_match = re.search(
        r"(?:require_clear_trend_for_signal|require_clear_trend|require_trend)\s*[:=]?\s*(true|false|1|0|yes|no|on|off)",
        raw,
        re.IGNORECASE,
    )
    if req_match:
        s = str(req_match.group(1)).strip().lower()
        updates["require_clear_trend_for_signal"] = s in ("1", "true", "yes", "on")

    # Timezone
    tz_val = _parse_tz_offset_hours(raw)
    if tz_val is not None:
        updates["tz_offset_hours"] = int(tz_val)
        
    # 3. Lists (Watch/Exclude)
    # "watch XAUUSD, EURUSD" (comma-separated list; stop before other tokens like entry=...)
    watch_match = re.search(
        r"watch\s*[:=]?\s*([a-zA-Z0-9]+(?:\s*,\s*[a-zA-Z0-9]+)*)",
        raw,
        re.IGNORECASE,
    )
    if watch_match:
        pairs = [p.strip().upper() for p in watch_match.group(1).split(",") if p.strip()]
        if pairs: updates["watch_pairs"] = pairs

    # "exclude GBPJPY" (comma-separated list; stop before other tokens)
    exclude_match = re.search(
        r"exclude\s*[:=]?\s*([a-zA-Z0-9]+(?:\s*,\s*[a-zA-Z0-9]+)*)",
        raw,
        re.IGNORECASE,
    )
    if exclude_match:
        pairs = [p.strip().upper() for p in exclude_match.group(1).split(",") if p.strip()]
        if pairs: updates["exclude_pairs"] = pairs
        
    # Note
    updates["note"] = raw
    return updates

def set_profile_from_text(user_id: int, text: str) -> str:
    """
    Apply parsed changes to the user's profile.
    """
    account = get_account(str(user_id))
    is_admin = bool(account and account.get("is_admin"))

    user_data = get_user(str(user_id))
    if not user_data:
        # Initialize default
        current_profile = UserProfile(user_id=str(user_id))
    else:
        # Load existing into Pydantic to validation (ignoring extra fields in DB for now)
        # We need to be careful not to lose 'name' etc which are not in UserProfile
        # Actually UserProfile model has fields, but DB might have 'name' at root?
        # Let's trust get_user returns the dict merging.
        # Ideally we separate account info vs profile info.
        # For this refactor, let's assume user_data corresponds mostly to UserProfile + name
        current_profile = UserProfile.parse_obj(user_data)

    # Enforce: non-admin users can update STR once per calendar day (based on user's timezone).
    # NOTE: We intentionally use the EXISTING stored timezone for the day-limit check.
    # This prevents changing tz in the same STR update to bypass the daily limit.
    default_tz = int(os.getenv("DEFAULT_TZ_OFFSET_HOURS", "8") or "8")
    tz_offset_hours = int(getattr(current_profile, "tz_offset_hours", default_tz) or default_tz)
    now = datetime.utcnow()
    local_now = now + timedelta(hours=tz_offset_hours)
    today_key = local_now.date().isoformat()

    last_day = get_last_str_update_day(str(user_id))
    if not is_admin and last_day == today_key:
        return (
            "⏳ STR шинэчлэл өдөрт 1 удаа зөвшөөрөгдөнө.\n"
            f"Өнөөдрийн (UTC{tz_offset_hours:+d}) өдөр дээр STR аль хэдийн шинэчлэгдсэн байна."
        )

    # Strategy builder mode: if OPENAI_API_KEY exists, compile free-text into strategies
    raw_text = text.strip()
    if raw_text.lower().startswith("str:"):
        raw_text = raw_text[4:].strip()

    # Parse updates early so we can store tz_offset_hours even in AI mode.
    parsed_updates = parse_str_command(text)
    requested_tz = parsed_updates.get("tz_offset_hours")

    compiled_profile: Dict[str, Any] = dict(user_data or {})
    # Always persist the user's note as the raw strategy text
    compiled_profile["note"] = raw_text
    if requested_tz is not None:
        compiled_profile["tz_offset_hours"] = int(requested_tz)

    if os.getenv("OPENAI_API_KEY"):
        try:
            # We only allow 1 active strategy per user.
            clean_text = _strip_tz_token(raw_text)
            res = build_strategies_from_str_text(user_text=clean_text, max_strategies=1)
            compiled_profile["strategy"] = res.strategies[0]
            compiled_profile["strategy_summary"] = res.summary

            # Compatibility: also set top-level engine params from the active strategy
            first = res.strategies[0]
            compiled_profile["trend_tf"] = first.get("trend_tf", compiled_profile.get("trend_tf", "H4"))
            compiled_profile["entry_tf"] = first.get("entry_tf", compiled_profile.get("entry_tf", "M15"))
            compiled_profile["min_rr"] = float(first.get("min_rr", compiled_profile.get("min_rr", 3.0)))
            compiled_profile["min_risk"] = float(first.get("min_risk", compiled_profile.get("min_risk", 0.0)))
            compiled_profile["blocks"] = first.get("blocks", compiled_profile.get("blocks", {}))

            # Save
            name = compiled_profile.get("name") or (account.get("name") if account else None) or f"User {user_id}"
            add_user(str(user_id), str(name), compiled_profile)
            set_last_str_update_at(str(user_id), now)
            set_last_str_update_day(str(user_id), today_key)

            lines = ["✅ STR стратеги амжилттай шинэчлэгдлээ."]
            if res.summary:
                lines.append(f"🧠 Товч: {res.summary}")
            s = res.strategies[0]
            lines.append(
                "📌 Active strategy:\n"
                f"- {s.get('name')} | trend={s.get('trend_tf')} entry={s.get('entry_tf')} minRR=1:{float(s.get('min_rr', 3.0)):.1f}"
            )
            return "\n".join(lines)
        except Exception as e:
            # Fall back to classic parsing if the AI builder fails
            compiled_profile["strategy_summary"] = f"AI parse failed: {e}"

    # Legacy parsing mode (no API key or AI failure)
    updates = parsed_updates
    updated_profile = current_profile.copy(update=updates)
    # Merge into compiled_profile (keep any extra keys)
    compiled_profile.update(updated_profile.model_dump())

    # Plan enforcement: clamp watch_pairs by plan max.
    try:
        from core.plans import clamp_pairs, effective_max_pairs, validate_pairs

        max_pairs = int(effective_max_pairs(compiled_profile))
        ok, err = validate_pairs(compiled_profile.get("watch_pairs"), max_pairs)
        compiled_profile["watch_pairs"] = clamp_pairs(compiled_profile.get("watch_pairs"), max_pairs)
    except Exception:
        ok, err = True, ""

    name = compiled_profile.get("name") or (account.get("name") if account else None) or f"User {user_id}"
    add_user(str(user_id), str(name), compiled_profile)
    set_last_str_update_at(str(user_id), now)
    set_last_str_update_day(str(user_id), today_key)

    msg_lines = ["✅ Profile Updated:"]
    if "risk_percent" in updates: msg_lines.append(f"- Risk: {updated_profile.risk_percent}%")
    if "min_rr" in updates: msg_lines.append(f"- Min RR: 1:{updated_profile.min_rr}")
    if "trend_tf" in updates: msg_lines.append(f"- Trend TF: {updated_profile.trend_tf}")
    if "entry_tf" in updates: msg_lines.append(f"- Entry TF: {updated_profile.entry_tf}")
    if "watch_pairs" in updates: msg_lines.append(f"- Watch: {updated_profile.watch_pairs}")

    if not ok and err:
        msg_lines.append(f"\n⚠️ {err} (Plan limit applied)")

    if len(msg_lines) == 1:
        return "✅ Note saved (No settings detected. Use 'Risk=1' etc format)."

    return "\n".join(msg_lines)

def format_profile_for_user(user_id: int) -> str:
    p = get_profile(user_id) # Returns dict
    # Convert to object for easy access
    prof = UserProfile.parse_obj(p)
    return (
        "<b>My Strategy Profile</b>\n"
        f"Risk: {prof.risk_percent}%\n"
        f"Min RR: 1:{prof.min_rr}\n"
        f"Trend TF: {prof.trend_tf}\n"
        f"Entry TF: {prof.entry_tf}\n"
        f"Timezone: UTC{int(getattr(prof, 'tz_offset_hours', 0)):+d}\n"
        f"Watch: {prof.watch_pairs if prof.watch_pairs else 'Default'}\n"
        f"Note: {prof.note or ''}"
    )

