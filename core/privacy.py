from __future__ import annotations

import os
from pathlib import Path


_TRUTHY = {"1", "true", "yes", "y", "on"}


def privacy_mode_enabled() -> bool:
    """Return True if the backend should avoid persisting user data locally.

    This is intended for deployments where user data must live only in the
    dashboard/Firebase layer.

    Env vars (either works):
    - JKM_PRIVACY_MODE=1
    - PRIVACY_MODE=1
    """

    raw = (os.getenv("JKM_PRIVACY_MODE") or os.getenv("PRIVACY_MODE") or "").strip().lower()
    return raw in _TRUTHY


def user_db_provider() -> str:
    """Return the configured user DB provider.
    
    Options:
    - "local" (default): sqlite user_profiles.db
    - "dashboard" or "firebase": use dashboard internal API
    """
    return (os.getenv("USER_DB_PROVIDER") or os.getenv("USER_ACCOUNTS_PROVIDER") or "local").strip().lower()


def should_use_dashboard_for_users() -> bool:
    """Return True if user data should come from dashboard (Firestore)."""
    provider = user_db_provider()
    return provider in {"dashboard", "firebase"} or privacy_mode_enabled()


def purge_local_user_artifacts(*, base_dir: Path | None = None, verbose: bool = False) -> int:
    """Best-effort cleanup of on-disk user-related artifacts.

    This is intended for production privacy deployments where user data must not
    remain on disk. Non-fatal by design.
    
    Returns:
        Number of files deleted.
    """

    try:
        root = base_dir or Path(__file__).resolve().parents[1]
    except Exception:
        return 0

    deleted_count = 0

    # Core user data files
    paths = [
        root / "user_profiles.db",
        root / "state" / "plugin_events.jsonl",
        root / "state" / "events_queue.db",
        root / "user_profiles.json",  # Legacy JSON profiles
    ]

    for p in paths:
        try:
            if p.exists():
                p.unlink()
                deleted_count += 1
                if verbose:
                    print(f"[privacy] Deleted: {p}")
        except Exception as e:
            if verbose:
                print(f"[privacy] Failed to delete {p}: {e}")

    # Per-user strategy files
    try:
        user_dir = root / "state" / "user_strategies"
        if user_dir.exists() and user_dir.is_dir():
            for fp in user_dir.glob("*.json"):
                try:
                    fp.unlink()
                    deleted_count += 1
                    if verbose:
                        print(f"[privacy] Deleted: {fp}")
                except Exception as e:
                    if verbose:
                        print(f"[privacy] Failed to delete {fp}: {e}")
    except Exception:
        pass

    # Per-user signal files (if any)
    try:
        signals_dir = root / "state" / "user_signals"
        if signals_dir.exists() and signals_dir.is_dir():
            for fp in signals_dir.glob("*"):
                try:
                    fp.unlink()
                    deleted_count += 1
                    if verbose:
                        print(f"[privacy] Deleted: {fp}")
                except Exception:
                    pass
    except Exception:
        pass

    return deleted_count


def enforce_privacy_on_startup(verbose: bool = True) -> None:
    """Called at application startup to enforce privacy mode.
    
    If PRIVACY_MODE=1:
    1. Purge any existing local user artifacts
    2. Log what was cleaned up
    
    This should be called early in worker_main.py or api_server.py.
    """
    if not privacy_mode_enabled():
        return
    
    if verbose:
        print("[privacy] Privacy mode enabled. Purging local user artifacts...")
    
    count = purge_local_user_artifacts(verbose=verbose)
    
    if verbose:
        if count > 0:
            print(f"[privacy] Purged {count} local user artifact(s).")
        else:
            print("[privacy] No local user artifacts found to purge.")
        print("[privacy] User data will be stored in Firestore via dashboard only.")
