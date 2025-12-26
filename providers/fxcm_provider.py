# providers/fxcm_provider.py
from typing import List, Dict, Any, Optional
from datetime import datetime
from .base import MarketDataProvider

class FXCMProvider(MarketDataProvider):
    """
    Placeholder for future FXCM implementation.
    Currently returns empty data or raises NotImplementedError.
    """
    def __init__(self, api_token: str = ""):
        self.api_token = api_token

    def get_candles(
        self, 
        symbol: str, 
        timeframe: str = "m5", 
        limit: int = 100, 
        since_ts: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        
        # Placeholder
        print(f"[FXCM] Fetching {symbol} {timeframe} (Mock/Empty)")
        return []

    def search_symbol(self, term: str) -> List[Dict[str, Any]]:
        return []
