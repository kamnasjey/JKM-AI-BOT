# watchlist_union.py
import json
import logging
from pathlib import Path
from typing import List, Set
from user_db import list_users
from user_profile import get_profile

logger = logging.getLogger(__name__)

def get_union_watchlist(max_per_user: int = 5) -> List[str]:
    """
    Scans all users, reads their active watchlist (max 5),
    and returns a unique union list of symbols.
    """
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
                    unique_symbols.add(s.upper().strip())

        # Exclusions (optional)
        exclude_pairs = profile.get("exclude_pairs", [])
        if isinstance(exclude_pairs, list):
            for s in exclude_pairs:
                if isinstance(s, str):
                    sym = s.upper().strip()
                    if sym:
                        unique_symbols.discard(sym)
                    
    # 3. Add default system pairs if list is empty (for safety/demo)
    if not unique_symbols:
        unique_symbols.update(["EURUSD", "XAUUSD", "BTCUSD"])
        
    return sorted(list(unique_symbols))
