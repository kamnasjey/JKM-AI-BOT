"""watchlist_union.py

In Massive-only production mode, the watchlist must be stable and deterministic.
We therefore load the canonical 15-symbol list from config/massive_symbols.json.

In other modes (e.g., simulation), we keep the legacy behavior of building a
union watchlist from user profiles.
"""

import json
import logging
import os
from pathlib import Path
from typing import List, Set

from user_db import list_users
from user_profile import get_profile

logger = logging.getLogger(__name__)


def _canon_symbol(sym: str) -> str:
    return str(sym or "").upper().strip().replace("/", "").replace(" ", "")


def _load_massive_watchlist() -> List[str]:
    cfg = Path("config/massive_symbols.json")
    if not cfg.exists():
        return []
    try:
        raw = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out = [_canon_symbol(x) for x in raw if isinstance(x, str) and str(x).strip()]
    out = sorted(list(dict.fromkeys([x for x in out if x])))
    return out


def _hard_default_massive_watchlist() -> List[str]:
    # Hard default per v0.1 spec (15 instruments)
    return [
        "EURUSD",
        "USDJPY",
        "GBPUSD",
        "AUDUSD",
        "USDCAD",
        "USDCHF",
        "NZDUSD",
        "EURJPY",
        "GBPJPY",
        "EURGBP",
        "AUDJPY",
        "EURAUD",
        "EURCHF",
        "XAUUSD",
        "BTCUSD",
    ]

def get_union_watchlist(max_per_user: int = 5) -> List[str]:
    """
    Scans all users, reads their active watchlist (max 5),
    and returns a unique union list of symbols.
    """
    # Massive-only mode: always use the canonical 15-symbol config.
    provider = (os.getenv("DATA_PROVIDER") or os.getenv("MARKET_DATA_PROVIDER") or "").strip().lower()
    if provider in ("massive", "massiveio", "massive_io"):
        wl = _load_massive_watchlist()
        return wl if wl else _hard_default_massive_watchlist()

    unique_symbols: Set[str] = set()
    
    # 1. Get all users
    try:
        users = list_users()
    except Exception as e:
        logger.error(f"Failed to list users for watchlist: {e}")
        return []
    
    # 2. Iterate and collect
    for u in users:
        user_id = str(u.get("user_id", ""))
        if not user_id:
            continue
            
        profile = get_profile(user_id)
        if not profile:
            continue
            
        user_pairs = profile.get("watch_pairs", [])
        if isinstance(user_pairs, list):
            # Take top N
            selected = user_pairs[:max_per_user]
            for s in selected:
                if isinstance(s, str):
                    unique_symbols.add(_canon_symbol(s))

        # Exclusions (optional)
        exclude_pairs = profile.get("exclude_pairs", [])
        if isinstance(exclude_pairs, list):
            for s in exclude_pairs:
                if isinstance(s, str):
                    sym = _canon_symbol(s)
                    if sym:
                        unique_symbols.discard(sym)
                    
    # 3. Add default system pairs if list is empty (for safety/demo)
    if not unique_symbols:
        unique_symbols.update(["EURUSD", "XAUUSD", "BTCUSD"])
        
    return sorted(list(unique_symbols))
