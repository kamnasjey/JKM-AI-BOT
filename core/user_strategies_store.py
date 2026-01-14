from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.atomic_io import atomic_write_text
from core.privacy import privacy_mode_enabled
from strategies.loader import load_strategies_from_profile

from services.dashboard_user_data_client import DashboardUserDataClient


def _repo_dir() -> Path:
    # core/ is at repo root/core
    return Path(__file__).resolve().parents[1]


def _base_dir() -> Path:
    """Resolve base directory for per-user strategies.

    Can be overridden via USER_STRATEGIES_DIR.

    - If env var is absolute, use it.
    - If env var is relative, resolve under repo root.
    """

    raw = str(os.getenv("USER_STRATEGIES_DIR", "state/user_strategies") or "state/user_strategies").strip()
    p = Path(raw)
    if p.is_absolute():
        return p
    return _repo_dir() / p


def user_strategies_path(user_id: str) -> Path:
    uid = str(user_id or "").strip() or "unknown"
    return _base_dir() / f"{uid}.json"


def load_user_strategies(user_id: str) -> List[Dict[str, Any]]:
    """Load per-user normalized strategy specs.

    Returns an empty list on missing/invalid content.
    """

    provider = (os.getenv("USER_STRATEGIES_PROVIDER") or "").strip().lower()
    if provider in {"firebase", "dashboard"}:
        client = DashboardUserDataClient.from_env()
        if client:
            try:
                remote = client.get_strategies(str(user_id))
                out = [dict(s) for s in remote if isinstance(s, dict)]
                if out:
                    return out

                # If dashboard storage is enabled but user has no strategies yet,
                # fall back to a safe built-in default (especially in privacy mode).
                auto_default = str(os.getenv("AUTO_DEFAULT_STRATEGY", "") or "").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
                if privacy_mode_enabled() or auto_default:
                    from core.default_strategies import get_default_user_strategies

                    return get_default_user_strategies()

                return []
            except Exception:
                # Resiliency: if dashboard fetch fails, fall back to local.
                if privacy_mode_enabled():
                    return []

    if privacy_mode_enabled():
        # In privacy mode we never read per-user local files.
        return []

    path = user_strategies_path(user_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except Exception:
        return []

    try:
        obj = json.loads(raw) if raw.strip() else {}
    except Exception:
        return []

    if not isinstance(obj, dict):
        return []

    strategies = obj.get("strategies")
    if not isinstance(strategies, list):
        return []

    # Ensure we always return list[dict]
    out: List[Dict[str, Any]] = []
    for it in strategies:
        if isinstance(it, dict):
            out.append(dict(it))
    return out


def validate_normalize_user_strategies(
    raw_items: Any,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Validate user-provided strategies (list of dict/JSON strings).

    Uses the existing strategy loader normalization + validation.
    Returns normalized specs and any loader errors.
    """

    items: List[Any]
    if isinstance(raw_items, list):
        items = list(raw_items)
    elif raw_items is None:
        items = []
    else:
        # Accept single strategy-like payload.
        items = [raw_items]

    res = load_strategies_from_profile({"strategies": items})
    return [dict(s) for s in (res.strategies or [])], [str(e) for e in (res.errors or [])]


MAX_STRATEGIES_PER_USER = 30  # Maximum number of strategies a user can create


def _save_user_strategies_local(user_id: str, normalized: List[Dict[str, Any]]) -> Dict[str, Any]:
    payload = {
        "schema_version": 1,
        "user_id": str(user_id or "unknown"),
        "updated_at": int(time.time()),
        "strategies": normalized,
    }

    path = user_strategies_path(user_id)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))

    return {
        "ok": True,
        "user_id": payload["user_id"],
        "schema_version": payload["schema_version"],
        "strategies": normalized,
    }


def save_user_strategies(user_id: str, raw_items: Any) -> Dict[str, Any]:
    """Validate + atomically persist per-user strategies.

    Returns payload with {ok, warnings, user_id, schema_version, strategies}.
    Max 30 strategies per user.
    """

    normalized, errors = validate_normalize_user_strategies(raw_items)
    
    # Enforce max strategies limit
    if len(normalized) > MAX_STRATEGIES_PER_USER:
        return {
            "ok": False,
            "error": f"Maximum {MAX_STRATEGIES_PER_USER} strategies allowed per user. You have {len(normalized)}.",
            "user_id": str(user_id or "unknown"),
            "strategies": [],
            "warnings": errors,
        }

    provider = (os.getenv("USER_STRATEGIES_PROVIDER") or "").strip().lower()

    if privacy_mode_enabled() and provider not in {"firebase", "dashboard"}:
        return {
            "ok": False,
            "error": "Privacy mode is enabled; local strategy storage is disabled. Set USER_STRATEGIES_PROVIDER=dashboard (or firebase).",
            "user_id": str(user_id or "unknown"),
            "strategies": [],
            "warnings": errors,
            "storage_provider": "disabled",
        }

    if provider in {"firebase", "dashboard"}:
        client = DashboardUserDataClient.from_env()
        if not client:
            if privacy_mode_enabled():
                return {
                    "ok": False,
                    "error": "USER_STRATEGIES_PROVIDER is dashboard/firebase, but DASHBOARD_USER_DATA_URL (or DASHBOARD_BASE_URL) / DASHBOARD_INTERNAL_API_KEY is missing.",
                    "user_id": str(user_id or "unknown"),
                    "strategies": [],
                    "warnings": errors,
                    "storage_provider": "dashboard",
                    "synced_to_dashboard": False,
                }

            local = _save_user_strategies_local(user_id, normalized)
            local["warnings"] = errors
            local["storage_provider"] = "local"
            local["synced_to_dashboard"] = False
            local["notice"] = "USER_STRATEGIES_PROVIDER is dashboard/firebase, but DASHBOARD_USER_DATA_URL (or DASHBOARD_BASE_URL) / DASHBOARD_INTERNAL_API_KEY is missing; saved locally."
            return local

        try:
            client.put_strategies(str(user_id), normalized)
            return {
                "ok": True,
                "user_id": str(user_id or "unknown"),
                "schema_version": 1,
                "strategies": normalized,
                "warnings": errors,
                "storage_provider": "dashboard",
                "synced_to_dashboard": True,
            }
        except Exception as exc:
            if privacy_mode_enabled():
                return {
                    "ok": False,
                    "error": f"Failed to sync strategies to dashboard: {exc}",
                    "user_id": str(user_id or "unknown"),
                    "strategies": [],
                    "warnings": errors,
                    "storage_provider": "dashboard",
                    "synced_to_dashboard": False,
                }

            # Ensure user changes are not lost if the dashboard is temporarily down.
            local = _save_user_strategies_local(user_id, normalized)
            local["warnings"] = errors
            local["storage_provider"] = "local"
            local["synced_to_dashboard"] = False
            local["error"] = f"Failed to sync strategies to dashboard: {exc}"
            return local

    if privacy_mode_enabled():
        return {
            "ok": False,
            "error": "Privacy mode is enabled; local strategy storage is disabled.",
            "user_id": str(user_id or "unknown"),
            "strategies": [],
            "warnings": errors,
            "storage_provider": "disabled",
        }

    local = _save_user_strategies_local(user_id, normalized)
    local["warnings"] = errors
    local["storage_provider"] = "local"
    return local
