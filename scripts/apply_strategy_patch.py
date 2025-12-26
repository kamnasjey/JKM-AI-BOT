from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, List

from pathlib import Path

from strategies.strategy_spec import StrategySpec

from core.atomic_io import atomic_append_jsonl_via_replace, atomic_write_text


@dataclass(frozen=True)
class PatchRecord:
    patch_id: str
    date: str
    strategy_id: str
    changes: Dict[str, Dict[str, Any]]
    before_snapshot: Dict[str, Any]
    after_snapshot: Dict[str, Any]


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _stable_patch_id(strategy_id: str, changes: Dict[str, Dict[str, Any]]) -> str:
    payload = {
        "strategy_id": str(strategy_id),
        "changes": changes,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:12]


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("JSON root must be an object")
    return obj


def save_json_atomic(data: Dict[str, Any], path: str) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    atomic_write_text(Path(path), text)


def backup_file(path: str) -> str:
    ts = _utc_ts()
    backup_path = f"{path}.bak.{ts}"
    shutil.copy2(path, backup_path)
    return backup_path


def append_patch_audit(
    *,
    audit_path: str,
    patch_id: str,
    patch_type: str,
    strategy_ids: List[str],
    file_path: str,
    backup_path: str,
    dry_run: bool,
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> None:
    """Append a single JSONL audit record (best-effort, non-fatal)."""
    try:
        os.makedirs(os.path.dirname(audit_path) or ".", exist_ok=True)
        rec = {
            "ts": int(datetime.now(timezone.utc).timestamp()),
            "patch_id": str(patch_id),
            "patch_type": str(patch_type or "NA"),
            "strategy_ids": list(strategy_ids or []),
            "file_path": str(file_path),
            "backup_path": str(backup_path),
            "dry_run": bool(dry_run),
            "before": dict(before or {}),
            "after": dict(after or {}),
        }
        atomic_append_jsonl_via_replace(Path(audit_path), json.dumps(rec, ensure_ascii=False))
    except Exception:
        return


def _find_strategy_index(data: Dict[str, Any], strategy_id: str) -> Optional[int]:
    strategies = data.get("strategies")
    if not isinstance(strategies, list):
        return None
    for i, s in enumerate(strategies):
        if not isinstance(s, dict):
            continue
        if str(s.get("strategy_id") or "").strip() == str(strategy_id):
            return i
    return None


def _apply_changes(strategy_obj: Dict[str, Any], changes: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    before: Dict[str, Any] = {}
    after: Dict[str, Any] = {}

    for k, spec in (changes or {}).items():
        if not isinstance(spec, dict):
            continue
        before[k] = strategy_obj.get(k)
        after_val = spec.get("to")
        strategy_obj[k] = after_val
        after[k] = after_val

    return before, after


def _validate_strategy(strategy_obj: Dict[str, Any]) -> Tuple[bool, str]:
    spec, errors = StrategySpec.from_dict(strategy_obj)
    if errors:
        return False, f"from_dict_errors={errors}"
    if spec is None:
        return False, "spec_is_none"

    ok, v_errors, _warnings = spec.validate()
    if not ok:
        return False, f"validate_errors={v_errors}"

    return True, ""


def apply_patch_workflow(
    *,
    strategies_path: str,
    strategy_id: str,
    changes: Dict[str, Dict[str, Any]],
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Apply patch changes to a strategy config file safely.

    Returns dict with keys:
      - ok
      - patch_id
      - backup_path (optional)
      - before_snapshot
      - after_snapshot
    """
    if not os.path.exists(strategies_path):
        raise FileNotFoundError(strategies_path)

    data = load_json(strategies_path)
    idx = _find_strategy_index(data, strategy_id)
    if idx is None:
        raise ValueError(f"strategy_id_not_found: {strategy_id}")

    strategies = data.get("strategies")
    assert isinstance(strategies, list)

    # Work on a copy first.
    new_data = copy.deepcopy(data)
    new_strategies = new_data.get("strategies")
    assert isinstance(new_strategies, list)

    strategy_obj = new_strategies[int(idx)]
    if not isinstance(strategy_obj, dict):
        raise ValueError("strategy_entry_not_a_dict")

    before_snapshot, after_snapshot = _apply_changes(strategy_obj, changes)

    ok, err = _validate_strategy(strategy_obj)
    if not ok:
        raise ValueError(f"validation_failed: {err}")

    patch_id = _stable_patch_id(strategy_id, changes)

    if dry_run:
        return {
            "ok": True,
            "patch_id": patch_id,
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
            "backup_path": None,
        }

    # Apply: backup then atomic replace
    backup_path = backup_file(strategies_path)
    save_json_atomic(new_data, strategies_path)

    return {
        "ok": True,
        "patch_id": patch_id,
        "before_snapshot": before_snapshot,
        "after_snapshot": after_snapshot,
        "backup_path": backup_path,
    }


def apply_patch_and_audit(
    *,
    strategies_path: str,
    strategy_id: str,
    changes: Dict[str, Dict[str, Any]],
    dry_run: bool,
    audit_path: str = "state/patch_audit.jsonl",
    patch_type: str = "NA",
    strategy_ids: Optional[List[str]] = None,
    backup_path_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply patch and (if apply) append an audit JSONL record."""
    res = apply_patch_workflow(
        strategies_path=strategies_path,
        strategy_id=strategy_id,
        changes=changes,
        dry_run=bool(dry_run),
    )

    if not bool(dry_run):
        backup_path = str(backup_path_override or res.get("backup_path") or "").strip()
        if backup_path:
            append_patch_audit(
                audit_path=str(audit_path),
                patch_id=str(res.get("patch_id") or ""),
                patch_type=str(patch_type or "NA"),
                strategy_ids=list(strategy_ids or [strategy_id]),
                file_path=str(strategies_path),
                backup_path=backup_path,
                dry_run=False,
                before=dict(res.get("before_snapshot") or {}),
                after=dict(res.get("after_snapshot") or {}),
            )

    return res


def load_patch_suggestions(path: str = "state/patch_suggestions.json") -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"schema": 1, "items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f) or {}
    except Exception:
        return {"schema": 1, "items": []}
    if not isinstance(obj, dict):
        return {"schema": 1, "items": []}
    items = obj.get("items")
    if not isinstance(items, list):
        items = []
    return {"schema": int(obj.get("schema") or 1), "items": items}


def find_patch_by_id(suggestions: Dict[str, Any], patch_id: str, *, strategy_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    items = suggestions.get("items")
    if not isinstance(items, list):
        return None
    pid = str(patch_id or "").strip()
    if not pid:
        return None
    for it in items:
        if not isinstance(it, dict):
            continue
        if str(it.get("patch_id") or "") != pid:
            continue
        if strategy_id is not None and str(it.get("strategy_id") or "") != str(strategy_id):
            continue
        return it
    return None


def _parse_patch_json(raw: str) -> Dict[str, Any]:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("patch_json_root_must_be_object")
    return obj


def main() -> int:
    p = argparse.ArgumentParser(description="Apply a recommended strategy patch safely (backup + validate + atomic write).")
    p.add_argument("--strategy", dest="strategy_id", type=str, default="", help="strategy_id to patch")
    p.add_argument("--patch_id", type=str, default="", help="patch_id from state/patch_suggestions.json")
    p.add_argument("--patch_json", type=str, default="", help="inline patch JSON (object)")
    p.add_argument("--strategies_path", type=str, default="config/strategies.json", help="path to strategies.json")
    p.add_argument("--suggestions_path", type=str, default="state/patch_suggestions.json", help="path to patch suggestions registry")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="actually write file (default is dry-run)")
    mode.add_argument("--dry-run", action="store_true", help="dry-run only")

    args = p.parse_args()

    dry_run = True
    if bool(args.apply):
        dry_run = False

    patch_id = str(args.patch_id or "").strip()
    patch_json = str(args.patch_json or "").strip()
    strategy_id = str(args.strategy_id or "").strip()

    try:
        print(f"PATCH_APPLY_START | patch_id={patch_id or 'NA'} | strategy_id={strategy_id or 'NA'} | dry_run={dry_run}")

        patch_type = "NA"
        strategy_ids: List[str] = []

        if patch_id:
            suggestions = load_patch_suggestions(str(args.suggestions_path))
            patch = find_patch_by_id(suggestions, patch_id, strategy_id=strategy_id or None)
            if patch is None:
                raise ValueError("patch_id_not_found")
            if not strategy_id:
                strategy_id = str(patch.get("strategy_id") or "").strip()
            changes = patch.get("changes")
            if not isinstance(changes, dict):
                raise ValueError("patch_changes_bad_shape")
            patch_type = str(patch.get("patch_type") or patch.get("type") or "NA")
            sids = patch.get("strategy_ids")
            if isinstance(sids, list):
                strategy_ids = [str(x) for x in sids if str(x).strip()]

        elif patch_json:
            patch = _parse_patch_json(patch_json)
            if not strategy_id:
                strategy_id = str(patch.get("strategy_id") or "").strip()
            changes = patch.get("changes") if isinstance(patch.get("changes"), dict) else patch
            if not isinstance(changes, dict):
                raise ValueError("patch_json_changes_bad_shape")
            if "strategy_id" in changes:
                # If user pasted full object, strip non-change keys
                changes = dict(changes)
                changes.pop("strategy_id", None)
            patch_type = str(patch.get("patch_type") or patch.get("type") or "NA")
            sids = patch.get("strategy_ids")
            if isinstance(sids, list):
                strategy_ids = [str(x) for x in sids if str(x).strip()]

        else:
            raise ValueError("missing_patch_id_or_patch_json")

        if not strategy_id:
            raise ValueError("missing_strategy_id")

        res = apply_patch_and_audit(
            strategies_path=str(args.strategies_path),
            strategy_id=strategy_id,
            changes=changes,
            dry_run=bool(dry_run),
            audit_path=os.getenv("PATCH_AUDIT_PATH", "state/patch_audit.jsonl"),
            patch_type=patch_type,
            strategy_ids=(strategy_ids or [strategy_id]),
        )

        print(
            "PATCH_APPLY_OK | "
            f"patch_id={res.get('patch_id')} | "
            f"strategy_id={strategy_id} | "
            f"dry_run={dry_run} | "
            f"backup={res.get('backup_path') or 'NA'}"
        )
        return 0

    except Exception as e:
        print(
            "PATCH_APPLY_FAILED | "
            f"patch_id={patch_id or 'NA'} | "
            f"strategy_id={strategy_id or 'NA'} | "
            f"err={type(e).__name__}:{e}"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
