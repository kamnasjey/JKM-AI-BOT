from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from providers.simulation_provider import SimulationProvider

from .base import DataProvider
from .models import Candle
from .normalize import normalize_candles


class SimulationDataProvider(DataProvider):
    name = "SIMULATION"

    def __init__(self) -> None:
        self._provider = SimulationProvider()

    def normalize_symbol(self, symbol: str) -> str:
        return str(symbol or "").strip().upper().replace("/", "").replace(" ", "")

    def fetch_candles(
        self,
        symbol: str,
        *,
        timeframe: str = "m5",
        max_count: int = 100,
        limit: Optional[int] = None,
        since_ts: Optional[datetime] = None,
        until_ts: Optional[datetime] = None,
    ) -> List[Candle]:
        effective_limit = int(limit) if limit is not None else int(max_count)
        raw = self._provider.get_candles(
            self.normalize_symbol(symbol),
            timeframe=str(timeframe).lower(),
            limit=effective_limit,
            since_ts=since_ts,
        )
        return normalize_candles(
            raw,
            provider=self.name,
            symbol=self.normalize_symbol(symbol),
            timeframe=timeframe,
            requested_limit=effective_limit,
        )

    def search_symbol(self, term: str) -> List[Dict[str, Any]]:
        return self._provider.search_symbol(term)
