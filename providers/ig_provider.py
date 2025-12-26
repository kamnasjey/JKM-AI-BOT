# providers/ig_provider.py
from typing import List, Dict, Any, Optional
from datetime import datetime
from .base import MarketDataProvider
from ig_client import IGClient

class IGProvider(MarketDataProvider):
    """
    Adapter for IGClient to fit MarketDataProvider interface.
    """
    def __init__(self, ig_client: IGClient):
        self.client = ig_client

    def get_candles(
        self, 
        symbol: str, 
        timeframe: str = "m5", 
        limit: int = 100, 
        since_ts: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        
        # Map timeframe to IG resolution
        # IG: MINUTE_5, HOUR_1, etc.
        tf_map = {
            "m1": "MINUTE",
            "m5": "MINUTE_5",
            "m15": "MINUTE_15",
            "h1": "HOUR",
            "h4": "HOUR_4",
            "d1": "DAY"
        }
        
        resolution = tf_map.get(timeframe.lower(), "MINUTE_5")
        
        # Resolve EPIC if simple symbol provided
        epic = self._resolve_epic(symbol)
        
        # Call original client
        # Note: ig_client.get_candles returns normalized list of dicts
        # [{'time': datetime, 'open': float...}]
        candles = self.client.get_candles(
            epic=epic, 
            resolution=resolution, 
            max_points=limit
        )
        
        # Filter by since_ts if provided
        if since_ts:
            candles = [c for c in candles if c['time'] > since_ts]
            
        return candles

    def _resolve_epic(self, symbol: str) -> str:
        s = symbol.replace("/", "").replace(" ", "").upper()
        # Basic Mapping (Can be expanded or moved to config/db)
        # Note: These are 'best guess' or standard CFDs.
        # User might need to customize this mapping.
        mapping = {
            "EURUSD": "CS.D.EURUSD.MINI.IP", # Use MINI for safety/commonality or CFD
            "GBPUSD": "CS.D.GBPUSD.MINI.IP",
            "USDJPY": "CS.D.USDJPY.CFD.IP",  # As found in Search
            "XAUUSD": "CS.D.CFDGOLD.CFDGC.IP",
            "GOLD": "CS.D.CFDGOLD.CFDGC.IP",
            "BTCUSD": "CS.D.BITCOIN.CFD.IP",
            "BITCOIN": "CS.D.BITCOIN.CFD.IP",
            "AUDUSD": "CS.D.AUDUSD.MINI.IP",
            "USDCAD": "CS.D.USDCAD.MINI.IP",
            "EURJPY": "CS.D.EURJPY.MINI.IP",
            "GBPJPY": "CS.D.GBPJPY.MINI.IP",
        }
        # Fallback: assume it is an EPIC if it has dots, else return mapped or original
        if "." in s:
            return s
        return mapping.get(s, s)

    def search_symbol(self, term: str) -> List[Dict[str, Any]]:
        # Not fully implemented in base IGClient but could be added
        return []
