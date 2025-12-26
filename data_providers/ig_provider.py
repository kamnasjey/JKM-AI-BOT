from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

from ig_client import IGClient

from .base import DataProvider
from .instruments import load_instruments_catalog, resolve_provider_symbol
from .models import Candle
from .normalize import normalize_candles


class IGDataProvider(DataProvider):
    name = "IG"

    def __init__(self, client: IGClient, *, catalog_path: Optional[str] = None):
        self._client = client
        self._catalog = load_instruments_catalog(catalog_path)

    def normalize_symbol(self, symbol: str) -> str:
        resolved = resolve_provider_symbol(self._catalog, symbol=symbol, provider_name=self.name)
        # If catalog doesn't have a mapping, fall back to env EPIC_*.
        # (Keeps EPIC exposure out of engine/cache; only used within provider.)
        canonical = str(symbol or "").strip().upper().replace("/", "").replace(" ", "")
        if resolved == canonical:
            env_val = os.getenv(f"EPIC_{canonical}")
            if env_val and env_val.strip():
                return env_val.strip()
        return resolved

    def fetch_candles(
        self,
        symbol: str,
        *,
        timeframe: str = "m5",
        max_count: int = 100,
        limit: Optional[int] = None,
        since_ts: Optional[datetime] = None,
    ) -> List[Candle]:
        effective_limit = int(limit) if limit is not None else int(max_count)
        tf_map = {
            "m1": "MINUTE",
            "m5": "MINUTE_5",
            "m15": "MINUTE_15",
            "h1": "HOUR",
            "h4": "HOUR_4",
            "d1": "DAY",
        }
        resolution = tf_map.get(str(timeframe).lower(), "MINUTE_5")
        epic = self.normalize_symbol(symbol)
        raw = self._client.get_candles(epic=epic, resolution=resolution, max_points=effective_limit)
        if since_ts is not None:
            raw = [c for c in raw if c.get("time") and c["time"] > since_ts]
        return normalize_candles(
            raw,
            provider=self.name,
            symbol=str(symbol).upper(),
            timeframe=timeframe,
            requested_limit=effective_limit,
        )
