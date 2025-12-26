# resample_5m.py
from typing import List, Dict, Any
from datetime import datetime, timedelta

def resample(candles_5m: List[Dict[str, Any]], timeframe: str) -> List[Dict[str, Any]]:
    """
    Resample 5m candles to higher timeframes (m15, h1, h4, d1).
    
    Args:
        candles_5m: List of 5m candles (must be sorted by time)
        timeframe: Target timeframe code ("m15", "h1", "h4", "d1")
        
    Returns:
        List of resampled candles
    """
    if not candles_5m:
        return []

    # Map timeframe to minutes
    tf_minutes = {
        "m5": 5,
        "m15": 15,
        "m30": 30,
        "h1": 60,
        "h4": 240,
        "d1": 1440
    }
    
    minutes = tf_minutes.get(timeframe.lower())
    if not minutes:
        raise ValueError(f"Unsupported timeframe for resampling: {timeframe}")
        
    if minutes == 5:
        return candles_5m # No change needed

    resampled = []
    current_bucket = None
    bucket_open_time = None
    
    # Init bucket vars
    agg_open = 0.0
    agg_high = -float('inf')
    agg_low = float('inf')
    agg_close = 0.0
    
    for c in candles_5m:
        t: datetime = c['time']
        
        # Determine bucket start time
        # E.g. for m15, 10:00 -> 10:00, 10:04 -> 10:00, 10:05 -> 10:00 ?? 
        # Standard: 10:00, 10:05, 10:10 belong to 10:00 bucket? 
        # Actually usually 10:00-10:15 candle includes 10:00, 10:05, 10:10.
        
        # Calculate start of the period
        # Total minutes from epoch or just simple math on hour/minute
        total_min = t.hour * 60 + t.minute
        remainder = total_min % minutes
        
        # If we are strictly aligned to day boundaries, we use timestamp math
        # simple approach: subtract remainder minutes
        bucket_start = t - timedelta(minutes=remainder, seconds=t.second, microseconds=t.microsecond)
        
        if current_bucket != bucket_start:
            # Close previous bucket if exists
            if current_bucket is not None:
                resampled.append({
                    'time': current_bucket,
                    'open': agg_open,
                    'high': agg_high,
                    'low': agg_low,
                    'close': agg_close
                })
            
            # Start new bucket
            current_bucket = bucket_start
            agg_open = c['open']
            agg_high = c['high']
            agg_low = c['low']
            agg_close = c['close']
        else:
            # Update current bucket
            agg_high = max(agg_high, c['high'])
            agg_low = min(agg_low, c['low'])
            agg_close = c['close']
            
    # Modify last bucket logic:
    # If the last bucket is incomplete (streaming data), we still usually return it as "forming"
    if current_bucket is not None:
         resampled.append({
            'time': current_bucket,
            'open': agg_open,
            'high': agg_high,
            'low': agg_low,
            'close': agg_close
        })
        
    return resampled
