# providers/simulation_provider.py
import math
import random
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from .base import MarketDataProvider

class SimulationProvider(MarketDataProvider):
    """
    Generates realistic looking random walk 5m candles.
    Useful for development without burning API limits or needing keys.
    """
    
    def __init__(self):
        self._last_candles: Dict[str, Dict[str, Any]] = {}
        # Simple starting prices for simulation
        self._prices = {
            "EURUSD": 1.1000,
            "GBPUSD": 1.2700,
            "USDJPY": 150.00,
            "XAUUSD": 2000.00,
            "BTCUSD": 65000.00,
        }
    
    def get_candles(
        self, 
        symbol: str, 
        timeframe: str = "m5", 
        limit: int = 100, 
        since_ts: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        
        if timeframe != "m5":
            # For simplicity, simulation only strictly supports m5, 
            # others could be derived or ignored in this MVP context.
            pass
            
        now = datetime.now(timezone.utc)
        # Round down to nearest 5m
        current_5m_ts = now.replace(second=0, microsecond=0)
        discard = current_5m_ts.minute % 5
        current_5m_ts -= timedelta(minutes=discard)
        
        # Determine start time
        if since_ts:
            start_ts = since_ts
            # If since_ts is very recent, we might return empty or just the forming candle
        else:
            start_ts = current_5m_ts - timedelta(minutes=5 * limit)
            
        candles = []
        
        # Base price logic
        base_price = self._prices.get(symbol, 100.0)
        volatility = base_price * 0.0005 # 0.05% per candle
        
        # Generate candles from start_ts up to current_5m_ts
        # We'll regenerate "history" consistently based on time seed if we wanted to be stateless,
        # but for simple polling we just walk forward.
        # To make it consistent for reloading, let's use a time-seeded random.
        
        # Ensure we don't generate more than limit
        # Calculate max possible candles between start and now
        delta_min = (current_5m_ts - start_ts).total_seconds() / 60
        count = int(delta_min // 5)
        if count <= 0:
            return []
            
        actual_limit = min(limit, count)
        # Adjust start if limit is tighter
        effective_start = current_5m_ts - timedelta(minutes=5 * actual_limit)
        
        # Generate
        # We use a deterministic approach based on timestamp hash so refreshing doesn't change history
        prev_close = base_price
        
        generated = []
        iter_ts = effective_start
        
        while iter_ts < current_5m_ts:
            # Seed based on symbol + time to be deterministic
            seed = f"{symbol}_{iter_ts.timestamp()}"
            rd = random.Random(seed)
            
            # Random walk
            change = (rd.random() - 0.5) * 2 * volatility
            open_p = prev_close
            close_p = open_p + change
            high_p = max(open_p, close_p) + (rd.random() * volatility * 0.5)
            low_p = min(open_p, close_p) - (rd.random() * volatility * 0.5)
            
            # Add some trend bias based on hour? Nah keep simple.
            
            c = {
                'time': iter_ts,
                'open': round(open_p, 5),
                'high': round(high_p, 5),
                'low': round(low_p, 5),
                'close': round(close_p, 5),
                'volume': int(rd.random() * 1000)
            }
            generated.append(c)
            
            prev_close = close_p
            iter_ts += timedelta(minutes=5)
            
        # Simulating "Live" candle? 
        # For now let's just return completed candles (up to previous 5m block)
        # To make it feel live, we could include the current incomplete candle?
        # The prompt asks for 5m candles. Usually providers return closed candles.
        
        return generated

    def search_symbol(self, term: str) -> List[Dict[str, Any]]:
        term = term.upper()
        results = []
        for s in self._prices.keys():
            if term in s:
                results.append({"symbol": s, "description": "Simulated Pair"})
        return results
