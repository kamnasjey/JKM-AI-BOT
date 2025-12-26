from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from strategies.loader import load_strategy_pack


def _unix_ts() -> int:
    try:
        return int(datetime.utcnow().timestamp())
    except Exception:
        return 0


def _read_latest_audit_entry(audit_path: str, patch_id: str) -> Optional[Dict[str, Any]]:
    pid = str(patch_id or "").strip()
    if not pid:
        return None
    if not os.path.exists(audit_path):
        return None

    latest: Optional[Dict[str, Any]] = None
    try:
        with open(audit_path, "r", encoding="utf-8") as f:
            for line in f:
                s = str(line or "").strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("patch_id") or "").strip() != pid:
                    continue
                latest = obj
    except Exception:
        return None

    return latest


def _atomic_write_bytes(dst_path: str, content: bytes) -> None:
    directory = os.path.dirname(dst_path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{dst_path}.tmp"
    with open(tmp, "wb") as f:
        f.write(content)
    os.replace(tmp, dst_path)


def _validate_strategies(path: str) -> bool:
    pack = load_strategy_pack(path, presets_dir="config/presets")
    # Treat hard file/schema errors as invalid.
    if pack.errors:
        return False
    # If enabled strategies exist but all invalid, fail.
    if not pack.strategies and pack.invalid_enabled:
        return False
    return True


def rollback_patch(
    *,
    patch_id: str,
    audit_path: str = "state/patch_audit.jsonl",
    strategies_path: str = "config/strategies.json",
    dry_run: bool = True,
    validate: bool = True,
) -> Dict[str, Any]:
    entry = _read_latest_audit_entry(audit_path, patch_id)
    if entry is None:
        raise ValueError("patch_id_not_found_in_audit")

    backup_path = str(entry.get("backup_path") or "").strip()
    if not backup_path:
        raise ValueError("audit_missing_backup_path")
    if not os.path.exists(backup_path):
        raise FileNotFoundError(backup_path)

    if dry_run:
        return {"ok": True, "patch_id": patch_id, "backup_path": backup_path, "dry_run": True}

    # Save current content for safe revert if validation fails.
    try:
        with open(strategies_path, "rb") as f:
            current_bytes = f.read()
    except Exception:
        current_bytes = b""

    with open(backup_path, "rb") as f:
        backup_bytes = f.read()

    _atomic_write_bytes(strategies_path, backup_bytes)

    if validate:
        if not _validate_strategies(strategies_path):
            # revert
            _atomic_write_bytes(strategies_path, current_bytes)
            raise ValueError("rollback_validation_failed")

    return {"ok": True, "patch_id": patch_id, "backup_path": backup_path, "dry_run": False}


def main() -> int:
    p = argparse.ArgumentParser(description="Rollback a strategy patch using state/patch_audit.jsonl (safe restore).")
    p.add_argument("--patch_id", type=str, required=True)
    p.add_argument("--audit_path", type=str, default="state/patch_audit.jsonl")
    p.add_argument("--strategies_path", type=str, default="config/strategies.json")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")

    p.add_argument("--no-validate", action="store_true", help="skip loader validation after restore")

    args = p.parse_args()

    dry_run = True
    if bool(args.apply):
        dry_run = False

    patch_id = str(args.patch_id or "").strip()

    try:
        entry = _read_latest_audit_entry(str(args.audit_path), patch_id)
        backup = str((entry or {}).get("backup_path") or "").strip() or "NA"
        print(f"PATCH_ROLLBACK_START | patch_id={patch_id} | backup={backup} | dry_run={dry_run}")

        res = rollback_patch(
            patch_id=patch_id,
            audit_path=str(args.audit_path),
            strategies_path=str(args.strategies_path),
            dry_run=bool(dry_run),
            validate=(not bool(args.no_validate)),
        )

        print(
            "PATCH_ROLLBACK_OK | "
            f"patch_id={patch_id} | "
            f"restored={str(args.strategies_path)} | "
            f"backup={res.get('backup_path') or 'NA'} | "
            f"dry_run={dry_run}"
        )
        return 0

    except Exception as e:
        print(f"PATCH_ROLLBACK_FAILED | patch_id={patch_id or 'NA'} | err={type(e).__name__}:{e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
