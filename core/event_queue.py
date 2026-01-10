"""Event Queue for async notification processing.

Core scan enqueues events here; Worker process consumes them.
Uses SQLite with WAL mode for concurrent access.
DB stored in state/events_queue.db (not tracked in git).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("core.event_queue")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_DB_PATH: Optional[Path] = None
_LOCK = threading.Lock()

def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        # Determine state dir (works inside container or host)
        state_dir = Path(os.getenv("STATE_DIR", "state"))
        state_dir.mkdir(parents=True, exist_ok=True)
        _DB_PATH = state_dir / "events_queue.db"
    return _DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_get_db_path()), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
_SCHEMA_QUEUE_EVENTS = """
CREATE TABLE IF NOT EXISTS queue_events (
    id TEXT PRIMARY KEY,
    created_ts INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    setup_type TEXT NOT NULL,
    setup_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NEW',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_ts INTEGER NOT NULL DEFAULT 0
);
"""

_SCHEMA_TELEGRAM_DELIVERIES = """
CREATE TABLE IF NOT EXISTS telegram_deliveries (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    setup_key TEXT NOT NULL,
    sent_ts INTEGER NOT NULL,
    cooldown_until_ts INTEGER NOT NULL
);
"""

_SCHEMA_CONNECT_TOKENS = """
CREATE TABLE IF NOT EXISTS connect_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_ts INTEGER NOT NULL,
    used_ts INTEGER
);
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_queue_status_next ON queue_events(status, next_attempt_ts);",
    "CREATE INDEX IF NOT EXISTS idx_delivery_user_setup ON telegram_deliveries(user_id, setup_key);",
    "CREATE INDEX IF NOT EXISTS idx_delivery_cooldown ON telegram_deliveries(cooldown_until_ts);",
    "CREATE INDEX IF NOT EXISTS idx_connect_expires ON connect_tokens(expires_ts);",
]


def init_db() -> None:
    """Initialize database schema. Safe to call multiple times."""
    with _LOCK:
        conn = _get_conn()
        try:
            conn.execute(_SCHEMA_QUEUE_EVENTS)
            conn.execute(_SCHEMA_TELEGRAM_DELIVERIES)
            conn.execute(_SCHEMA_CONNECT_TOKENS)
            for idx in _INDEXES:
                conn.execute(idx)
            conn.commit()
            logger.info("event_queue: DB initialized at %s", _get_db_path())
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Queue Events API
# ---------------------------------------------------------------------------
@dataclass
class QueueEvent:
    id: str
    created_ts: int
    symbol: str
    tf: str
    setup_type: str
    setup_key: str
    payload: Dict[str, Any]
    status: str
    attempts: int
    next_attempt_ts: int


def enqueue_event(
    symbol: str,
    tf: str,
    setup_type: str,
    setup_key: str,
    payload: Dict[str, Any],
) -> Optional[str]:
    """Enqueue a new event. Returns event_id or None on failure.
    
    MUST be fast and non-blocking. Errors are logged but not raised.
    """
    event_id = str(uuid.uuid4())
    now_ts = int(time.time())
    
    # Sanitize payload: never store secrets
    safe_payload = {k: v for k, v in payload.items() if "token" not in k.lower() and "secret" not in k.lower()}
    payload_json = json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":"))
    
    try:
        conn = _get_conn()
        try:
            conn.execute(
                """
                INSERT INTO queue_events (id, created_ts, symbol, tf, setup_type, setup_key, payload_json, status, attempts, next_attempt_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW', 0, 0)
                """,
                (event_id, now_ts, symbol.upper(), tf.upper(), setup_type, setup_key, payload_json),
            )
            conn.commit()
            return event_id
        finally:
            conn.close()
    except Exception as e:
        logger.error("enqueue_event failed: %s", type(e).__name__)
        return None


def claim_events(limit: int = 50, lock_s: int = 60) -> List[QueueEvent]:
    """Claim up to `limit` NEW events, marking them PROCESSING.
    
    Returns list of QueueEvent. Worker should process and mark_done/mark_failed.
    """
    now_ts = int(time.time())
    unlock_ts = now_ts + lock_s
    
    results: List[QueueEvent] = []
    
    try:
        conn = _get_conn()
        try:
            # Select events that are NEW or FAILED with next_attempt_ts <= now
            cursor = conn.execute(
                """
                SELECT * FROM queue_events
                WHERE (status = 'NEW' OR (status = 'FAILED' AND next_attempt_ts <= ?))
                ORDER BY created_ts ASC
                LIMIT ?
                """,
                (now_ts, limit),
            )
            rows = cursor.fetchall()
            
            ids = []
            for row in rows:
                ids.append(row["id"])
                payload = {}
                try:
                    payload = json.loads(row["payload_json"] or "{}")
                except Exception:
                    pass
                results.append(QueueEvent(
                    id=row["id"],
                    created_ts=row["created_ts"],
                    symbol=row["symbol"],
                    tf=row["tf"],
                    setup_type=row["setup_type"],
                    setup_key=row["setup_key"],
                    payload=payload,
                    status=row["status"],
                    attempts=row["attempts"],
                    next_attempt_ts=row["next_attempt_ts"],
                ))
            
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE queue_events SET status='PROCESSING', attempts=attempts+1, next_attempt_ts=? WHERE id IN ({placeholders})",
                    [unlock_ts] + ids,
                )
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error("claim_events failed: %s", type(e).__name__)
    
    return results


def mark_done(event_id: str) -> bool:
    """Mark event as DONE."""
    try:
        conn = _get_conn()
        try:
            conn.execute("UPDATE queue_events SET status='DONE' WHERE id=?", (event_id,))
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.error("mark_done failed: %s", type(e).__name__)
        return False


def mark_failed(event_id: str, retry_after_s: int = 60) -> bool:
    """Mark event as FAILED with retry scheduled."""
    now_ts = int(time.time())
    next_ts = now_ts + retry_after_s
    
    try:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE queue_events SET status='FAILED', next_attempt_ts=? WHERE id=?",
                (next_ts, event_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.error("mark_failed failed: %s", type(e).__name__)
        return False


def get_queue_stats() -> Dict[str, int]:
    """Get queue statistics for monitoring."""
    stats = {"NEW": 0, "PROCESSING": 0, "DONE": 0, "FAILED": 0, "total": 0}
    try:
        conn = _get_conn()
        try:
            cursor = conn.execute("SELECT status, COUNT(*) as cnt FROM queue_events GROUP BY status")
            for row in cursor:
                stats[row["status"]] = row["cnt"]
                stats["total"] += row["cnt"]
        finally:
            conn.close()
    except Exception:
        pass
    return stats


# ---------------------------------------------------------------------------
# Telegram Delivery Dedupe/Cooldown
# ---------------------------------------------------------------------------
def delivery_recent(user_id: str, setup_key: str, now_ts: Optional[int] = None) -> bool:
    """Check if this setup was recently delivered to this user (cooldown active)."""
    if now_ts is None:
        now_ts = int(time.time())
    
    try:
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "SELECT cooldown_until_ts FROM telegram_deliveries WHERE user_id=? AND setup_key=? ORDER BY sent_ts DESC LIMIT 1",
                (user_id, setup_key),
            )
            row = cursor.fetchone()
            if row and row["cooldown_until_ts"] > now_ts:
                return True
            return False
        finally:
            conn.close()
    except Exception:
        return False


def record_delivery(user_id: str, setup_key: str, now_ts: Optional[int] = None, cooldown_s: int = 1800) -> bool:
    """Record a delivery for dedupe tracking."""
    if now_ts is None:
        now_ts = int(time.time())
    
    delivery_id = str(uuid.uuid4())
    cooldown_until = now_ts + cooldown_s
    
    try:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO telegram_deliveries (id, user_id, setup_key, sent_ts, cooldown_until_ts) VALUES (?, ?, ?, ?, ?)",
                (delivery_id, user_id, setup_key, now_ts, cooldown_until),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.error("record_delivery failed: %s", type(e).__name__)
        return False


def cleanup_old_deliveries(older_than_days: int = 7) -> int:
    """Remove old delivery records."""
    cutoff_ts = int(time.time()) - (older_than_days * 86400)
    deleted = 0
    try:
        conn = _get_conn()
        try:
            cursor = conn.execute("DELETE FROM telegram_deliveries WHERE sent_ts < ?", (cutoff_ts,))
            deleted = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    return deleted


# ---------------------------------------------------------------------------
# Connect Tokens API
# ---------------------------------------------------------------------------
def create_connect_token(user_id: str, expires_in_s: int = 1800) -> Optional[str]:
    """Create a one-time connect token for Telegram deep link."""
    token = str(uuid.uuid4()).replace("-", "")[:24]
    now_ts = int(time.time())
    expires_ts = now_ts + expires_in_s
    
    try:
        conn = _get_conn()
        try:
            conn.execute(
                "INSERT INTO connect_tokens (token, user_id, expires_ts, used_ts) VALUES (?, ?, ?, NULL)",
                (token, user_id, expires_ts),
            )
            conn.commit()
            return token
        finally:
            conn.close()
    except Exception as e:
        logger.error("create_connect_token failed: %s", type(e).__name__)
        return None


def validate_connect_token(token: str) -> Optional[str]:
    """Validate and consume a connect token. Returns user_id if valid."""
    now_ts = int(time.time())
    
    try:
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "SELECT user_id, expires_ts, used_ts FROM connect_tokens WHERE token=?",
                (token,),
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            if row["used_ts"] is not None:
                return None  # Already used
            if row["expires_ts"] < now_ts:
                return None  # Expired
            
            # Mark as used
            conn.execute("UPDATE connect_tokens SET used_ts=? WHERE token=?", (now_ts, token))
            conn.commit()
            
            return row["user_id"]
        finally:
            conn.close()
    except Exception as e:
        logger.error("validate_connect_token failed: %s", type(e).__name__)
        return None


def cleanup_old_tokens(older_than_days: int = 7) -> int:
    """Remove old/expired tokens."""
    cutoff_ts = int(time.time()) - (older_than_days * 86400)
    deleted = 0
    try:
        conn = _get_conn()
        try:
            cursor = conn.execute("DELETE FROM connect_tokens WHERE expires_ts < ?", (cutoff_ts,))
            deleted = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    return deleted
