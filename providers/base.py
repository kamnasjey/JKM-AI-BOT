# providers/base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime

class MarketDataProvider(ABC):
    """
    Abstract Base Class for Market Data Providers.
    """

    @abstractmethod
    def get_candles(
        self, 
        symbol: str, 
        timeframe: str = "m5", 
        limit: int = 100, 
        since_ts: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch candles for a symbol.
        
        Args:
            symbol: e.g. "EUR/USD" or "XAUUSD"
            timeframe: e.g. "m5", "m15", "h1" - Implementation should focus on m5
            limit: max number of candles
            since_ts: fetch candles after this timestamp (optional)
            
        Returns:
            List of dicts: [
                {
                    'time': datetime_object_utc, 
                    'open': float, 
                    'high': float, 
                    'low': float, 
                    'close': float, 
                    'volume': float (optional)
                }, 
                ...
            ]
        """
        pass

    @abstractmethod
    def search_symbol(self, term: str) -> List[Dict[str, Any]]:
        """
        Search for tradeable symbols.
        Returns: [{'symbol': 'EURUSD', 'description': 'Euro vs USD'}, ...]
        """
        pass
