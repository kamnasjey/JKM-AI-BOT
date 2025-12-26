from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_catalog_path() -> Path:
    # Primary location (per provider layer design)
    p = Path(__file__).resolve().parent / "instruments.json"
    if p.exists():
        return p
    # Back-compat: older repo-root instruments.json
    return _repo_root() / "instruments.json"


def load_instruments_catalog(path: Optional[str] = None) -> Dict[str, Any]:
    """Load instruments mapping.

    Format example:
      {
        "XAUUSD": {"IG": "CS.D.CFDGOLD.CFDGC.IP"},
        "EURUSD": {"IG": "CS.D.EURUSD.MINI.IP"}
      }
    """
    p = Path(path) if path else _default_catalog_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_provider_symbol(
    catalog: Dict[str, Any],
    *,
    symbol: str,
    provider_name: str,
) -> str:
    s = str(symbol or "").strip().upper().replace("/", "").replace(" ", "")
    if not s:
        return s

    entry = catalog.get(s)
    if isinstance(entry, dict):
        # Catalog keys are provider names like "IG", "OANDA".
        val = entry.get(provider_name.upper()) or entry.get(provider_name.lower())
        if isinstance(val, str) and val.strip():
            return val.strip()

    return s
