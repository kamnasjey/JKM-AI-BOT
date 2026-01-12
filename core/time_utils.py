from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


ULAANBAATAR_TZ_NAME = "Asia/Ulaanbaatar"


def get_ulaanbaatar_tz() -> timezone:
    """Return Ulaanbaatar timezone.

    Prefers IANA tz database; falls back to fixed UTC+8.
    """

    if ZoneInfo is not None:
        try:
            # Mongolia is UTC+8 year-round (no DST).
            return ZoneInfo(ULAANBAATAR_TZ_NAME)  # type: ignore[return-value]
        except Exception:
            pass

    return timezone(timedelta(hours=8), name=ULAANBAATAR_TZ_NAME)


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    # IMPORTANT: We intentionally do NOT treat plain ints/floats as timestamps here,
    # because candle `time` might already be an exchange-specific index/epoch unit.
    # We only convert ISO/datetime forms.

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    return None


def to_ulaanbaatar_iso(value: Any) -> Any:
    """Convert a datetime/ISO string to Ulaanbaatar ISO string.

    Returns the original value if it can't be parsed as datetime.
    """

    dt = _parse_dt(value)
    if dt is None:
        return value

    return dt.astimezone(get_ulaanbaatar_tz()).isoformat()
