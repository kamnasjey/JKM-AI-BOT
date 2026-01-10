from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.atomic_io import atomic_write_text
from strategies.loader import load_strategies_from_profile


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


def save_user_strategies(user_id: str, raw_items: Any) -> Dict[str, Any]:
    """Validate + atomically persist per-user strategies.

    Returns payload with {ok, warnings, user_id, schema_version, strategies}.
    """

    normalized, errors = validate_normalize_user_strategies(raw_items)

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
        "warnings": errors,
    }


# ---------------------------------------------------------------------------
# Helper: get enabled symbols for a user (for pair quota + worker routing)
# ---------------------------------------------------------------------------
def get_enabled_symbols_for_user(user_id: str) -> set:
    """Return set of distinct symbols with enabled strategies for this user.
    
    A symbol is considered enabled if ANY strategy with enabled=True references it
    in the 'symbols' list. If a strategy has no 'symbols' list, it applies to ALL
    symbols (returned as special marker '__ALL__').
    """
    strategies = load_user_strategies(user_id)
    symbols: set = set()
    
    for strat in strategies:
        if not isinstance(strat, dict):
            continue
        # Check if strategy is enabled
        enabled = strat.get("enabled", True)
        if not enabled:
            continue
        
        # Get symbols list
        strat_symbols = strat.get("symbols")
        if not strat_symbols or not isinstance(strat_symbols, list):
            # No symbols filter means ALL symbols
            symbols.add("__ALL__")
        else:
            for sym in strat_symbols:
                if isinstance(sym, str) and sym.strip():
                    symbols.add(sym.strip().upper())
    
    return symbols


def count_enabled_symbols(user_id: str) -> int:
    """Count distinct enabled symbols for a user.
    
    Returns 999 if '__ALL__' is present (no symbol restriction).
    """
    symbols = get_enabled_symbols_for_user(user_id)
    if "__ALL__" in symbols:
        return 999  # Effectively unlimited
    return len(symbols)


def user_has_symbol_enabled(user_id: str, symbol: str) -> bool:
    """Check if user has this symbol enabled via any strategy."""
    symbols = get_enabled_symbols_for_user(user_id)
    if "__ALL__" in symbols:
        return True
    return symbol.strip().upper() in symbols
