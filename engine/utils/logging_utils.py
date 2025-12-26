"""engine.utils.logging_utils

Small helpers for 24/7 ops logging.

- `make_scan_id()` creates a short unique id for correlating logs.
- `log_kv()` formats a single-line, human-readable key=value log.

No external dependencies.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict


def make_scan_id() -> str:
    """Return a short unique scan id: unix_ms + random suffix."""
    unix_ms = int(time.time() * 1000)
    suffix = secrets.token_hex(2)  # 4 hex chars
    return f"{unix_ms}-{suffix}"


def _fmt_value(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        # keep one-line
        return v.replace("\n", " ").replace("\r", " ")
    if isinstance(v, (list, tuple, dict)):
        try:
            return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return str(v)
    return str(v)


def log_kv(logger, msg: str, **kv: Any) -> None:
    """Log `msg` plus `key=value` pairs in one line."""
    parts = [msg]
    for k in sorted(kv.keys()):
        parts.append(f"{k}={_fmt_value(kv[k])}")
    logger.info(" | ".join(parts))


def log_kv_error(logger, msg: str, **kv: Any) -> None:
    """Same as log_kv, but logs at error level with stack trace."""
    parts = [msg]
    for k in sorted(kv.keys()):
        parts.append(f"{k}={_fmt_value(kv[k])}")
    logger.error(" | ".join(parts), exc_info=True)


def log_kv_warning(logger, msg: str, **kv: Any) -> None:
    parts = [msg]
    for k in sorted(kv.keys()):
        parts.append(f"{k}={_fmt_value(kv[k])}")
    logger.warning(" | ".join(parts))


def merge_kv(*items: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for d in items:
        out.update(d)
    return out
