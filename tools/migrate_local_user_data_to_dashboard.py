#!/usr/bin/env python3
"""
migrate_local_user_data_to_dashboard.py

Migration script to move local user data (sqlite + strategy files) to Firestore
via the dashboard's internal API.

This script reads:
1. user_profiles.db (sqlite) - user identity, prefs, telegram settings
2. state/user_strategies/*.json - per-user strategy files
3. user_profiles.db signals table - legacy signals (optional)

And writes to Firestore via dashboard API endpoints.

Usage:
    python tools/migrate_local_user_data_to_dashboard.py [--dry-run] [--verbose]
    
Options:
    --dry-run    Preview changes without writing to dashboard
    --verbose    Show detailed output
    --skip-signals  Skip signal migration (can be slow for large datasets)

Prerequisites:
    - DASHBOARD_BASE_URL or DASHBOARD_USER_DATA_URL set
    - DASHBOARD_INTERNAL_API_KEY set
    - Local user_profiles.db and/or strategy files exist

Example:
    # Preview what would be migrated
    python tools/migrate_local_user_data_to_dashboard.py --dry-run --verbose
    
    # Run actual migration
    python tools/migrate_local_user_data_to_dashboard.py
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.dashboard_user_data_client import DashboardUserDataClient


def log(msg: str, verbose_only: bool = False, verbose: bool = False) -> None:
    if verbose_only and not verbose:
        return
    print(msg)


def get_local_users(db_path: str) -> List[Dict[str, Any]]:
    """Read users from local sqlite database."""
    if not os.path.exists(db_path):
        return []
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    rows = conn.execute("""
        SELECT 
            user_id, name, email, profile_json,
            telegram_chat_id, telegram_enabled, telegram_connected_ts,
            is_admin, email_verified, created_at
        FROM users
    """).fetchall()
    
    conn.close()
    
    users = []
    for row in rows:
        profile = {}
        if row["profile_json"]:
            try:
                profile = json.loads(row["profile_json"])
            except json.JSONDecodeError:
                profile = {}
        
        users.append({
            "user_id": row["user_id"],
            "name": row["name"],
            "email": row["email"],
            "profile": profile,
            "telegram_chat_id": row["telegram_chat_id"],
            "telegram_enabled": bool(row["telegram_enabled"]) if row["telegram_enabled"] is not None else None,
            "telegram_connected_ts": row["telegram_connected_ts"],
            "is_admin": bool(row["is_admin"]),
            "email_verified": bool(row["email_verified"]) if row["email_verified"] is not None else False,
            "created_at": row["created_at"],
        })
    
    return users


def get_local_strategies(user_id: str, strategies_dir: Path) -> Optional[List[Dict[str, Any]]]:
    """Read strategies from local JSON file."""
    path = strategies_dir / f"{user_id}.json"
    if not path.exists():
        return None
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        strategies = data.get("strategies", [])
        if isinstance(strategies, list):
            return strategies
    except (json.JSONDecodeError, IOError):
        pass
    
    return None


def get_local_signals(db_path: str, user_id: str) -> List[Dict[str, Any]]:
    """Read signals from local sqlite database."""
    if not os.path.exists(db_path):
        return []
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        rows = conn.execute("""
            SELECT 
                signal_key, user_id, pair, direction, timeframe,
                entry, sl, tp, rr, strategy_name,
                generated_at, status, resolved_at, resolved_price, meta_json
            FROM signals
            WHERE user_id = ?
            ORDER BY generated_at DESC
            LIMIT 500
        """, (user_id,)).fetchall()
    except sqlite3.OperationalError:
        # Table doesn't exist
        conn.close()
        return []
    
    conn.close()
    
    signals = []
    for row in rows:
        meta = {}
        if row["meta_json"]:
            try:
                meta = json.loads(row["meta_json"])
            except json.JSONDecodeError:
                meta = {}
        
        signals.append({
            "signal_key": row["signal_key"],
            "user_id": row["user_id"],
            "symbol": row["pair"],
            "pair": row["pair"],
            "direction": row["direction"],
            "timeframe": row["timeframe"],
            "entry": float(row["entry"] or 0),
            "sl": float(row["sl"] or 0),
            "tp": float(row["tp"] or 0),
            "rr": float(row["rr"] or 0),
            "strategy_name": row["strategy_name"],
            "generated_at": row["generated_at"],
            "status": row["status"],
            "resolved_at": row["resolved_at"],
            "resolved_price": float(row["resolved_price"]) if row["resolved_price"] else None,
            "meta": meta,
        })
    
    return signals


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate local user data to dashboard (Firestore)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--skip-signals", action="store_true", help="Skip signal migration")
    args = parser.parse_args()
    
    dry_run = args.dry_run
    verbose = args.verbose
    skip_signals = args.skip_signals
    
    print("=== Local → Dashboard User Data Migration ===")
    print(f"Mode: {'DRY RUN (no writes)' if dry_run else 'LIVE'}")
    print(f"Signals: {'SKIPPED' if skip_signals else 'INCLUDED'}")
    print("")
    
    # Initialize dashboard client
    client = DashboardUserDataClient.from_env()
    if not client:
        print("✗ Error: Dashboard client not configured.")
        print("  Set DASHBOARD_BASE_URL and DASHBOARD_INTERNAL_API_KEY.")
        sys.exit(1)
    
    print(f"✓ Dashboard client: {client.base_url}")
    
    # Check dashboard health
    if not dry_run:
        try:
            health = client.health_check(skip_prisma=True)
            if not health.get("ok"):
                print(f"✗ Dashboard health check failed: {health}")
                sys.exit(1)
            print("✓ Dashboard health OK")
        except Exception as e:
            print(f"✗ Dashboard health check error: {e}")
            sys.exit(1)
    
    print("")
    
    # Determine paths
    repo_root = Path(__file__).resolve().parents[1]
    db_path = str(repo_root / "user_profiles.db")
    strategies_dir = repo_root / "state" / "user_strategies"
    
    log(f"DB path: {db_path}", verbose_only=True, verbose=verbose)
    log(f"Strategies dir: {strategies_dir}", verbose_only=True, verbose=verbose)
    
    # Read local users
    users = get_local_users(db_path)
    print(f"Found {len(users)} users in local database")
    
    # Also check for strategy files without DB entries
    extra_user_ids = set()
    if strategies_dir.exists():
        for fp in strategies_dir.glob("*.json"):
            uid = fp.stem
            if uid not in {u["user_id"] for u in users}:
                extra_user_ids.add(uid)
    
    if extra_user_ids:
        print(f"Found {len(extra_user_ids)} additional users with strategy files only")
    
    print("")
    
    # Migration stats
    stats = {
        "users_migrated": 0,
        "strategies_migrated": 0,
        "signals_migrated": 0,
        "errors": 0,
    }
    
    # Process users from DB
    for user in users:
        user_id = user["user_id"]
        print(f"Processing: {user_id} ({user.get('email') or 'no email'})")
        
        # Prepare identity data
        profile = user.get("profile", {}) or {}
        identity = {
            "email": user.get("email"),
            "name": user.get("name") or profile.get("name"),
            "has_paid_access": profile.get("plan") not in (None, "", "free"),
            "plan": profile.get("plan"),
            "plan_status": profile.get("plan_status"),
        }
        
        # Prepare prefs data
        prefs = {
            "telegram_chat_id": user.get("telegram_chat_id"),
            "telegram_enabled": user.get("telegram_enabled"),
            "telegram_connected_ts": user.get("telegram_connected_ts"),
            "scan_enabled": profile.get("scan_enabled"),
        }
        
        log(f"  Identity: {identity}", verbose_only=True, verbose=verbose)
        log(f"  Prefs: {prefs}", verbose_only=True, verbose=verbose)
        
        if dry_run:
            print(f"  [DRY RUN] Would sync identity + prefs")
        else:
            try:
                client.put_user_full(user_id, identity, prefs)
                print(f"  ✓ Synced identity + prefs")
                stats["users_migrated"] += 1
            except Exception as e:
                print(f"  ✗ Error syncing user: {e}")
                stats["errors"] += 1
        
        # Migrate strategies
        strategies = get_local_strategies(user_id, strategies_dir)
        if strategies:
            log(f"  Found {len(strategies)} strategies", verbose_only=True, verbose=verbose)
            
            if dry_run:
                print(f"  [DRY RUN] Would sync {len(strategies)} strategies")
            else:
                try:
                    client.put_strategies(user_id, strategies)
                    print(f"  ✓ Synced {len(strategies)} strategies")
                    stats["strategies_migrated"] += len(strategies)
                except Exception as e:
                    print(f"  ✗ Error syncing strategies: {e}")
                    stats["errors"] += 1
        
        # Migrate signals
        if not skip_signals:
            signals = get_local_signals(db_path, user_id)
            if signals:
                log(f"  Found {len(signals)} signals", verbose_only=True, verbose=verbose)
                
                if dry_run:
                    print(f"  [DRY RUN] Would sync {len(signals)} signals")
                else:
                    signal_errors = 0
                    for sig in signals:
                        try:
                            client.upsert_signal(
                                user_id=user_id,
                                signal_key=sig["signal_key"],
                                signal=sig,
                            )
                            stats["signals_migrated"] += 1
                        except Exception as e:
                            signal_errors += 1
                            log(f"    ✗ Signal error: {e}", verbose_only=True, verbose=verbose)
                    
                    if signal_errors:
                        print(f"  ✓ Synced {len(signals) - signal_errors}/{len(signals)} signals ({signal_errors} errors)")
                        stats["errors"] += signal_errors
                    else:
                        print(f"  ✓ Synced {len(signals)} signals")
    
    # Process strategy-only users
    for user_id in extra_user_ids:
        print(f"Processing (strategies only): {user_id}")
        
        strategies = get_local_strategies(user_id, strategies_dir)
        if strategies:
            if dry_run:
                print(f"  [DRY RUN] Would sync {len(strategies)} strategies")
            else:
                try:
                    client.put_strategies(user_id, strategies)
                    print(f"  ✓ Synced {len(strategies)} strategies")
                    stats["strategies_migrated"] += len(strategies)
                except Exception as e:
                    print(f"  ✗ Error syncing strategies: {e}")
                    stats["errors"] += 1
    
    # Summary
    print("")
    print("=== Migration Summary ===")
    print(f"Users migrated: {stats['users_migrated']}")
    print(f"Strategies migrated: {stats['strategies_migrated']}")
    print(f"Signals migrated: {stats['signals_migrated']}")
    print(f"Errors: {stats['errors']}")
    
    if dry_run:
        print("")
        print("This was a DRY RUN. Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
