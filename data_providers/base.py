from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import Candle


class DataProvider(ABC):
    """Provider interface.

    Important: callers always use canonical symbols like "XAUUSD", "EURUSD".
    Provider-specific mapping (IG EPIC etc.) happens inside normalize_symbol().
    """

    name: str

    @abstractmethod
    def normalize_symbol(self, symbol: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def fetch_candles(
        self,
        symbol: str,
        *,
        timeframe: str = "m5",
        max_count: int = 100,
        limit: Optional[int] = None,
        since_ts: Optional[datetime] = None,
    ) -> List[Candle]:
        raise NotImplementedError

    def fetch_latest_price(self, symbol: str) -> Optional[float]:
        return None

    def search_symbol(self, term: str) -> List[Dict[str, Any]]:
        return []
