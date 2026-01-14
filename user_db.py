from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from config import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_NAME,
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_TELEGRAM,
)

DB_PATH = os.getenv("USER_DB_PATH", "user_profiles.db")
PBKDF2_ITERATIONS = 320_000
EMAIL_VERIFY_TTL_HOURS = 24


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = _get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE,
            name TEXT,
            profile_json TEXT,
            email TEXT UNIQUE,
            password_hash TEXT,
            telegram_handle TEXT,
            is_admin INTEGER DEFAULT 0,
            last_str_update_at TEXT,
            email_verified INTEGER DEFAULT 0,
            email_verified_at TEXT,
            email_verification_token_hash TEXT,
            email_verification_expires_at TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()

    existing_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    migrations = {
        "email": "ALTER TABLE users ADD COLUMN email TEXT",
        "password_hash": "ALTER TABLE users ADD COLUMN password_hash TEXT",
        "telegram_handle": "ALTER TABLE users ADD COLUMN telegram_handle TEXT",
        "is_admin": "ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0",
        "last_str_update_at": "ALTER TABLE users ADD COLUMN last_str_update_at TEXT",
        "email_verified": "ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0",
        "email_verified_at": "ALTER TABLE users ADD COLUMN email_verified_at TEXT",
        "email_verification_token_hash": "ALTER TABLE users ADD COLUMN email_verification_token_hash TEXT",
        "email_verification_expires_at": "ALTER TABLE users ADD COLUMN email_verification_expires_at TEXT",
        "created_at": "ALTER TABLE users ADD COLUMN created_at TEXT",
        # Telegram connect columns (v0.2)
        "telegram_chat_id": "ALTER TABLE users ADD COLUMN telegram_chat_id TEXT",
        "telegram_enabled": "ALTER TABLE users ADD COLUMN telegram_enabled INTEGER DEFAULT 1",
        "telegram_connected_ts": "ALTER TABLE users ADD COLUMN telegram_connected_ts INTEGER",
    }
    for column, ddl in migrations.items():
        if column not in existing_cols:
            conn.execute(ddl)
    conn.commit()
    conn.close()


def _hash_password(password: str) -> str:
    if not password:
        raise ValueError("Нууц үг шаардлагатай.")
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return base64.b64encode(salt + derived).decode("utf-8")


def _verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        return False
    try:
        payload = base64.b64decode(stored_hash.encode("utf-8"))
    except Exception:
        return False
    salt = payload[:16]
    digest = payload[16:]
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(candidate, digest)


def _row_to_account(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    profile = {}
    if row["profile_json"]:
        try:
            profile = json.loads(row["profile_json"])
        except json.JSONDecodeError:
            profile = {}
    return {
        "user_id": row["user_id"],
        "name": row["name"],
        "email": row["email"],
        "telegram_handle": row["telegram_handle"],
        "is_admin": bool(row["is_admin"]),
        "email_verified": bool(row["email_verified"]) if "email_verified" in row.keys() else False,
        "email_verified_at": row["email_verified_at"] if "email_verified_at" in row.keys() else None,
        "created_at": row["created_at"],
        "profile": profile,
    }


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_account(
    *,
    name: str,
    email: str,
    password: str,
    telegram_handle: str = "",
    profile: Optional[Dict[str, Any]] = None,
    is_admin: bool = False,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    email_norm = email.strip().lower()
    if not email_norm:
        raise ValueError("Имэйл шаардлагатай.")
    if len(password) < 8:
        raise ValueError("Нууц үг хамгийн багадаа 8 тэмдэгт байна.")

    init_db()
    conn = _get_connection()
    prof = dict(profile or {})
    try:
        from core.plans import normalize_plan_id

        if "plan" not in prof or not str(prof.get("plan") or "").strip():
            prof["plan"] = "free"
        else:
            prof["plan"] = normalize_plan_id(prof.get("plan"))

        if "plan_status" not in prof or not str(prof.get("plan_status") or "").strip():
            prof["plan_status"] = "active"
    except Exception:
        # Never block account creation due to plan helpers.
        prof.setdefault("plan", "free")
        prof.setdefault("plan_status", "active")

    profile_json = json.dumps(prof)
    hashed = _hash_password(password)
    assigned_id = user_id or uuid4().hex
    now = datetime.utcnow().isoformat()

    # Admin/service accounts are considered verified.
    email_verified = 1 if is_admin else 0
    email_verified_at = now if is_admin else None

    try:
        conn.execute(
            """
            INSERT INTO users (
                user_id, name, profile_json, email, password_hash, telegram_handle,
                is_admin, email_verified, email_verified_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assigned_id,
                name,
                profile_json,
                email_norm,
                hashed,
                telegram_handle,
                1 if is_admin else 0,
                email_verified,
                email_verified_at,
                now,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("Имэйл аль хэдийн бүртгэлтэй байна.") from exc
    finally:
        conn.close()

    account = get_account(assigned_id)
    if account is None:
        raise RuntimeError("Аккаунт үүсгэх үед алдаа гарлаа.")
    return account


def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    if not email or not password:
        return None
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE lower(email)=lower(?)",
        (email.strip(),),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    stored = row["password_hash"]
    if not stored or not _verify_password(password, stored):
        return None
    return _row_to_account(row)


def create_email_verification(*, email: str) -> Optional[str]:
    """Create and store a verification code for an existing user (by email).

    Returns the raw 6-digit code to be sent via email.
    If user doesn't exist or already verified, returns None.
    """
    email_norm = (email or "").strip().lower()
    if not email_norm:
        return None
    init_db()
    conn = _get_connection()
    row = conn.execute(
        "SELECT user_id, email_verified FROM users WHERE lower(email)=lower(?)",
        (email_norm,),
    ).fetchone()
    if row is None:
        conn.close()
        return None
    if bool(row["email_verified"]):
        conn.close()
        return None

    # 6-digit numeric code
    code = f"{secrets.randbelow(1_000_000):06d}"
    token_hash = _hash_token(code)
    expires_at = (datetime.utcnow()).timestamp() + EMAIL_VERIFY_TTL_HOURS * 3600
    expires_iso = datetime.utcfromtimestamp(expires_at).isoformat()
    now = datetime.utcnow().isoformat()

    conn.execute(
        """
        UPDATE users
        SET email_verification_token_hash=?, email_verification_expires_at=?
        WHERE lower(email)=lower(?)
        """,
        (token_hash, expires_iso, email_norm),
    )
    conn.commit()
    conn.close()
    return code


def verify_email_code(*, email: str, code: str) -> Optional[Dict[str, Any]]:
    """Verify email using (email + 6-digit code)."""
    email_norm = (email or "").strip().lower()
    code = (code or "").strip()
    if not email_norm or not code:
        return None
    token_hash = _hash_token(code)

    conn = _get_connection()
    row = conn.execute(
        """
        SELECT * FROM users
        WHERE lower(email)=lower(?) AND email_verification_token_hash=?
        """,
        (email_norm, token_hash),
    ).fetchone()
    if row is None:
        conn.close()
        return None
    expires_raw = row["email_verification_expires_at"] if "email_verification_expires_at" in row.keys() else None
    if not expires_raw:
        conn.close()
        return None
    try:
        expires_at = datetime.fromisoformat(str(expires_raw))
    except Exception:
        conn.close()
        return None
    if expires_at <= datetime.utcnow():
        conn.close()
        return None

    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        UPDATE users
        SET email_verified=1,
            email_verified_at=?,
            email_verification_token_hash=NULL,
            email_verification_expires_at=NULL
        WHERE lower(email)=lower(?) AND email_verification_token_hash=?
        """,
        (now, email_norm, token_hash),
    )
    conn.commit()
    conn.close()
    return get_account(row["user_id"])


def verify_email_token(*, token: str) -> Optional[Dict[str, Any]]:
    """Backward-compatible: treat token as a global code (no email binding).

    Prefer verify_email_code(email, code). This is kept for older links.
    """
    token = (token or "").strip()
    if not token:
        return None
    token_hash = _hash_token(token)
    conn = _get_connection()
    row = conn.execute(
        """
        SELECT * FROM users
        WHERE email_verification_token_hash=?
        """,
        (token_hash,),
    ).fetchone()
    if row is None:
        conn.close()
        return None
    expires_raw = row["email_verification_expires_at"] if "email_verification_expires_at" in row.keys() else None
    if not expires_raw:
        conn.close()
        return None
    try:
        expires_at = datetime.fromisoformat(str(expires_raw))
    except Exception:
        conn.close()
        return None
    if expires_at <= datetime.utcnow():
        conn.close()
        return None

    now = datetime.utcnow().isoformat()
    conn.execute(
        """
        UPDATE users
        SET email_verified=1,
            email_verified_at=?,
            email_verification_token_hash=NULL,
            email_verification_expires_at=NULL
        WHERE email_verification_token_hash=?
        """,
        (now, token_hash),
    )
    conn.commit()
    conn.close()
    return get_account(row["user_id"])


def get_account(user_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_connection()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (str(user_id),)).fetchone()
    conn.close()
    return _row_to_account(row)


def get_account_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE lower(email)=lower(?)",
        (email.strip(),),
    ).fetchone()
    conn.close()
    return _row_to_account(row)


def add_user(user_id: str, name: str, profile: Dict[str, Any]):
    init_db()
    profile_json = json.dumps(profile)
    conn = _get_connection()
    existing = conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE users SET name=?, profile_json=? WHERE user_id=?",
            (name, profile_json, user_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO users (user_id, name, profile_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, name, profile_json, datetime.utcnow().isoformat()),
        )
    conn.commit()
    conn.close()


def set_user_plan(
    *,
    user_id: str,
    plan_id: str,
    plan_status: str = "active",
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a user's plan in their stored profile JSON.

    We keep this inside the profile_json for minimal migrations.
    Also clamps watch_pairs to plan max to ensure server-side enforcement.
    """

    init_db()
    account = get_account(str(user_id))
    if not account:
        # Create minimal record if missing.
        add_user(str(user_id), f"User {user_id}", {"user_id": str(user_id)})
        account = get_account(str(user_id))

    prof = get_user(str(user_id)) or {}
    if not isinstance(prof, dict):
        prof = {}

    from core.plans import clamp_pairs, normalize_plan_id, plan_max_pairs

    pid = normalize_plan_id(plan_id)
    prof["plan"] = pid
    prof["plan_status"] = str(plan_status or "active")

    if stripe_customer_id is not None:
        prof["stripe_customer_id"] = str(stripe_customer_id)
    if stripe_subscription_id is not None:
        prof["stripe_subscription_id"] = str(stripe_subscription_id)

    max_pairs = int(plan_max_pairs(pid))
    prof["watch_pairs"] = clamp_pairs(prof.get("watch_pairs"), max_pairs)

    # Preserve display name.
    name = (
        prof.get("name")
        or (account.get("name") if isinstance(account, dict) else None)
        or f"User {user_id}"
    )
    prof["name"] = name

    add_user(str(user_id), str(name), prof)
    return get_user(str(user_id)) or prof


def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    account = get_account(user_id)
    if not account:
        return None
    profile = account.get("profile", {}) or {}
    if "name" not in profile:
        profile["name"] = account.get("name")
    profile["user_id"] = account.get("user_id")
    return profile


def list_users() -> List[Dict[str, Any]]:
    provider = (os.getenv("USER_ACCOUNTS_PROVIDER") or "").strip().lower()
    if provider in {"dashboard", "firebase"}:
        try:
            from services.dashboard_user_data_client import DashboardUserDataClient

            client = DashboardUserDataClient.from_env()
            if client:
                users = client.list_active_users()
                out: List[Dict[str, Any]] = []
                for u in users:
                    if not isinstance(u, dict):
                        continue
                    # Keep compatibility with existing caller expectations.
                    uid = str(u.get("user_id") or "").strip()
                    if not uid:
                        continue
                    out.append({
                        "user_id": uid,
                        "name": u.get("name"),
                        "email": u.get("email"),
                        "telegram_chat_id": u.get("telegram_chat_id"),
                        "telegram_enabled": u.get("telegram_enabled"),
                        "scan_enabled": u.get("scan_enabled"),
                        "plan": u.get("plan"),
                    })
                return out
        except Exception:
            # Fall back to local DB.
            pass

    conn = _get_connection()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    result: List[Dict[str, Any]] = []
    for row in rows:
        profile = _row_to_account(row)
        if not profile:
            continue
        data = profile["profile"] or {}
        data["user_id"] = profile["user_id"]
        data["name"] = profile.get("name")
        data["email"] = profile.get("email")
        data["telegram_handle"] = profile.get("telegram_handle")
        result.append(data)
    return result


def delete_user(user_id: str):
    conn = _get_connection()
    conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def ensure_admin_account(default_profile: Optional[Dict[str, Any]] = None) -> None:
    if not DEFAULT_ADMIN_EMAIL or not DEFAULT_ADMIN_PASSWORD:
        return
    if get_account_by_email(DEFAULT_ADMIN_EMAIL):
        return
    try:
        create_account(
            name=DEFAULT_ADMIN_NAME or "JKM Admin",
            email=DEFAULT_ADMIN_EMAIL,
            password=DEFAULT_ADMIN_PASSWORD,
            telegram_handle=DEFAULT_ADMIN_TELEGRAM or "",
            profile=default_profile or {},
            is_admin=True,
        )
    except ValueError:
        # Email already exists or password invalid – ignore
        return


def import_json_profiles(json_path: str = "user_profiles.json") -> None:
    if not os.path.exists(json_path):
        print(f"{json_path} олдсонгүй.")
        return
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for user_id, profile in data.items():
        add_user(user_id, profile.get("name", ""), profile)
    print(f"{len(data)} профайл импортлолоо.")


def test_db():
    print("DB init...")
    init_db()
    print("Add user...")
    add_user("123", "TestUser", {"name": "TestUser", "min_rr": 2.0})
    print("Get user...")
    u = get_user("123")
    print(u)
    print("List users...")
    print(list_users())
    print("Delete user...")
    delete_user("123")
    print(list_users())


def get_last_str_update_at(user_id: str) -> Optional[datetime]:
    """Return last STR update timestamp (UTC) for this user_id."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT last_str_update_at FROM users WHERE user_id=?",
        (str(user_id),),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    raw = row["last_str_update_at"]
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except Exception:
        return None


def set_last_str_update_at(user_id: str, when: datetime) -> None:
    """Set last STR update timestamp (UTC) for this user_id."""
    init_db()
    conn = _get_connection()
    conn.execute(
        "UPDATE users SET last_str_update_at=? WHERE user_id=?",
        (when.isoformat(), str(user_id)),
    )
    conn.commit()
    conn.close()


def get_last_str_update_day(user_id: str) -> Optional[str]:
    """Return last STR update day marker (e.g. '2025-12-19') for this user_id."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT last_str_update_day FROM users WHERE user_id=?",
        (str(user_id),),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    raw = row["last_str_update_day"]
    return str(raw) if raw else None


def set_last_str_update_day(user_id: str, day: str) -> None:
    """Set last STR update day marker for this user_id."""
    init_db()
    conn = _get_connection()
    conn.execute(
        "UPDATE users SET last_str_update_day=? WHERE user_id=?",
        (str(day), str(user_id)),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Telegram Connect Functions (v0.2)
# ---------------------------------------------------------------------------
def set_telegram_chat(user_id: str, chat_id: str) -> bool:
    """Bind a Telegram chat_id to a user."""
    provider = (os.getenv("USER_TELEGRAM_PROVIDER") or os.getenv("USER_ACCOUNTS_PROVIDER") or "").strip().lower()
    now_ts = int(datetime.utcnow().timestamp())

    # Canonical write (Firestore via dashboard) if enabled.
    if provider in {"dashboard", "firebase"}:
        try:
            from services.dashboard_user_data_client import DashboardUserDataClient

            client = DashboardUserDataClient.from_env()
            if client:
                client.put_user_prefs(
                    str(user_id),
                    {
                        "telegram_chat_id": str(chat_id),
                        "telegram_connected_ts": now_ts,
                        "telegram_enabled": True,
                    },
                )
        except Exception:
            pass

        # Canonical storage is dashboard; do not persist locally.
        return True

    init_db()
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE users SET telegram_chat_id=?, telegram_connected_ts=?, telegram_enabled=1 WHERE user_id=?",
            (str(chat_id), now_ts, str(user_id)),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_telegram_chat(user_id: str) -> Optional[str]:
    """Get Telegram chat_id for a user."""
    provider = (os.getenv("USER_TELEGRAM_PROVIDER") or os.getenv("USER_ACCOUNTS_PROVIDER") or "").strip().lower()
    if provider in {"dashboard", "firebase"}:
        try:
            from services.dashboard_user_data_client import DashboardUserDataClient

            client = DashboardUserDataClient.from_env()
            if client:
                prefs = client.get_user_prefs(str(user_id))
                chat = prefs.get("telegram_chat_id")
                if chat:
                    return str(chat)
        except Exception:
            pass

        return None

    conn = _get_connection()
    row = conn.execute(
        "SELECT telegram_chat_id FROM users WHERE user_id=?",
        (str(user_id),),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return row["telegram_chat_id"] if row["telegram_chat_id"] else None


def set_telegram_enabled(user_id: str, enabled: bool) -> bool:
    """Enable/disable Telegram notifications for a user."""
    provider = (os.getenv("USER_TELEGRAM_PROVIDER") or os.getenv("USER_ACCOUNTS_PROVIDER") or "").strip().lower()
    if provider in {"dashboard", "firebase"}:
        try:
            from services.dashboard_user_data_client import DashboardUserDataClient

            client = DashboardUserDataClient.from_env()
            if client:
                client.put_user_prefs(str(user_id), {"telegram_enabled": bool(enabled)})
        except Exception:
            pass

            # Canonical storage is dashboard; do not persist locally.
            return True

    init_db()
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE users SET telegram_enabled=? WHERE user_id=?",
            (1 if enabled else 0, str(user_id)),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_telegram_enabled(user_id: str) -> bool:
    """Check if Telegram notifications are enabled for a user."""
    provider = (os.getenv("USER_TELEGRAM_PROVIDER") or os.getenv("USER_ACCOUNTS_PROVIDER") or "").strip().lower()
    if provider in {"dashboard", "firebase"}:
        try:
            from services.dashboard_user_data_client import DashboardUserDataClient

            client = DashboardUserDataClient.from_env()
            if client:
                prefs = client.get_user_prefs(str(user_id))
                if "telegram_enabled" in prefs:
                    return bool(prefs.get("telegram_enabled"))
        except Exception:
            pass

        return True

    conn = _get_connection()
    row = conn.execute(
        "SELECT telegram_enabled FROM users WHERE user_id=?",
        (str(user_id),),
    ).fetchone()
    conn.close()
    if row is None:
        return False
    val = row["telegram_enabled"]
    return bool(val) if val is not None else True  # Default enabled


def list_users_with_telegram() -> List[Dict[str, Any]]:
    """List all users who have connected Telegram and have it enabled."""
    provider = (os.getenv("USER_TELEGRAM_PROVIDER") or os.getenv("USER_ACCOUNTS_PROVIDER") or "").strip().lower()
    if provider in {"dashboard", "firebase"}:
        try:
            from services.dashboard_user_data_client import DashboardUserDataClient

            client = DashboardUserDataClient.from_env()
            if client:
                users = client.list_active_users()
                out: List[Dict[str, Any]] = []
                for u in users:
                    if not isinstance(u, dict):
                        continue
                    uid = str(u.get("user_id") or "").strip()
                    chat = u.get("telegram_chat_id")
                    enabled = u.get("telegram_enabled")
                    if uid and chat and (enabled is None or bool(enabled)):
                        out.append({"user_id": uid, "chat_id": str(chat)})
                return out
        except Exception:
            pass

        return []

    conn = _get_connection()
    rows = conn.execute(
        "SELECT user_id, telegram_chat_id, telegram_enabled FROM users WHERE telegram_chat_id IS NOT NULL AND telegram_enabled=1"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            "user_id": row["user_id"],
            "chat_id": row["telegram_chat_id"],
        })
    return result


# Ensure DB is ready at import
init_db()


if __name__ == "__main__":
    import_json_profiles()
    test_db()
