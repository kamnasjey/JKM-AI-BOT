from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.atomic_io import atomic_append_jsonl_via_replace
from core.signal_payload_public_v1 import SignalPayloadPublicV1
from core.signal_payload_v1 import SignalPayloadV1


REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SIGNALS_PATH = REPO_DIR / "state" / "signals_v1.jsonl"
DEFAULT_PUBLIC_SIGNALS_PATH = REPO_DIR / "state" / "signals.jsonl"


def append_signal_jsonl(payload: SignalPayloadV1, path: Optional[Path] = None) -> None:
    if path is None:
        path = DEFAULT_SIGNALS_PATH
    obj = payload.model_dump(mode="json")
    signal_id = str(obj.get("signal_id") or "").strip()
    if not signal_id:
        obj["signal_id"] = uuid.uuid4().hex
    line = json.dumps(obj, ensure_ascii=False)
    atomic_append_jsonl_via_replace(path, line)


def append_public_signal_jsonl(
    public_payload: SignalPayloadPublicV1 | Dict[str, Any],
    path: Optional[Path] = None,
) -> None:
    """Append public/UI signal payload to JSONL (atomic, NA-safe).

    This is additive and does not change legacy storage.
    """

    if path is None:
        path = DEFAULT_PUBLIC_SIGNALS_PATH

    if isinstance(public_payload, SignalPayloadPublicV1):
        obj: Dict[str, Any] = public_payload.model_dump(mode="json")
    else:
        obj = dict(public_payload)

    signal_id = str(obj.get("signal_id") or "").strip()
    if not signal_id:
        obj["signal_id"] = uuid.uuid4().hex
    line = json.dumps(obj, ensure_ascii=False)
    atomic_append_jsonl_via_replace(path, line)


def _iter_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []


def _resolve_default_read_path(path: Path) -> Path:
    return path


def list_signals_jsonl(
    *,
    user_id: str,
    limit: int = 50,
    symbol: Optional[str] = None,
    path: Optional[Path] = None,
    include_all_users: bool = False,
) -> List[Dict[str, Any]]:
    if path is None:
        path = DEFAULT_SIGNALS_PATH
    limit = max(1, min(int(limit or 50), 500))
    sym = str(symbol).upper().strip() if symbol else None

    out: List[Dict[str, Any]] = []
    read_path = _resolve_default_read_path(path)
    lines = _iter_lines(read_path)

    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        if not include_all_users:
            if str(obj.get("user_id")) != str(user_id):
                continue

        if sym and str(obj.get("symbol") or "").upper() != sym:
            continue

        out.append(obj)
        if len(out) >= limit:
            break

    return out


def list_public_signals_jsonl(
    *,
    user_id: str,
    limit: int = 50,
    symbol: Optional[str] = None,
    path: Optional[Path] = None,
    include_all_users: bool = False,
) -> List[Dict[str, Any]]:
    """List public signals from JSONL.

    Contract:
    - Missing/empty file => []
    - Ignores blank/invalid lines
    - Reverse chronological (last line first)
    """

    return list_signals_jsonl(
        user_id=user_id,
        limit=limit,
        symbol=symbol,
        path=(path or DEFAULT_PUBLIC_SIGNALS_PATH),
        include_all_users=include_all_users,
    )


def get_signal_by_id_jsonl(
    *,
    user_id: str,
    signal_id: str,
    path: Optional[Path] = None,
    include_all_users: bool = False,
) -> Optional[Dict[str, Any]]:
    if path is None:
        path = DEFAULT_SIGNALS_PATH
    target = str(signal_id).strip()
    if not target:
        return None

    read_path = _resolve_default_read_path(path)
    lines = _iter_lines(read_path)
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue

        if str(obj.get("signal_id")) != target:
            continue

        if not include_all_users and str(obj.get("user_id")) != str(user_id):
            return None

        return obj

    return None


def get_public_signal_by_id_jsonl(
    *,
    user_id: str,
    signal_id: str,
    path: Optional[Path] = None,
    include_all_users: bool = False,
) -> Optional[Dict[str, Any]]:
    """Get one public signal by id from JSONL.

    Contract:
    - Missing/empty file => None
    - Ignores blank/invalid lines
    """

    return get_signal_by_id_jsonl(
        user_id=user_id,
        signal_id=signal_id,
        path=(path or DEFAULT_PUBLIC_SIGNALS_PATH),
        include_all_users=include_all_users,
    )
