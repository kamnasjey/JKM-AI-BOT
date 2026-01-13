#!/usr/bin/env python3
"""Debug the actual URL being generated and test it."""
import os
import sys
sys.path.insert(0, "/app")

from datetime import datetime, timezone, timedelta
import requests

def _dt_to_unix(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp())

# Same logic as massive_provider.py
end = datetime.now(timezone.utc)
limit = 5
tf_seconds = 300  # 5 minutes
use_start = end - timedelta(seconds=int(limit) * int(tf_seconds) * 4)

start_ts = _dt_to_unix(use_start)
end_ts = _dt_to_unix(end)

API_KEY = os.getenv("POLYGON_API_KEY", "13pxjpTe80GhXDijoB_3s4QVbo6CBKN7")
BASE_URL = "https://api.polygon.io"

symbols = ["C:EURUSD", "C:USDJPY", "C:GBPUSD", "C:AUDUSD", "C:XAUUSD", "X:BTCUSD"]

print(f"Time range: {use_start} to {end}")
print(f"Timestamps: {start_ts} to {end_ts}")
print(f"Duration: {(end_ts - start_ts) / 60:.1f} minutes")
print()

for sym in symbols:
    url = f"{BASE_URL}/v2/aggs/ticker/{sym}/range/5/minute/{start_ts}/{end_ts}"
    params = {"adjusted": "true", "sort": "desc", "limit": 5, "apiKey": API_KEY}
    
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    count = data.get("resultsCount", 0)
    status = data.get("status", "?")
    
    print(f"{sym}: {count} results, status={status}")
    if count > 0 and "results" in data:
        latest = data["results"][0]
        latest_ts = latest.get("t", 0) / 1000  # ms to sec
        latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
        print(f"  Latest candle: {latest_dt}")

print("\n--- Testing with date string format ---")
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
for sym in symbols[:2]:
    url = f"{BASE_URL}/v2/aggs/ticker/{sym}/range/5/minute/{today}/{today}"
    params = {"adjusted": "true", "sort": "desc", "limit": 5, "apiKey": API_KEY}
    
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()
    count = data.get("resultsCount", 0)
    print(f"{sym} (date string): {count} results")
