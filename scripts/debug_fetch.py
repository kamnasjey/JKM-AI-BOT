#!/usr/bin/env python3
"""Debug script to test Polygon API fetching."""
import os
import sys
import requests

# Ensure we're in the app directory
sys.path.insert(0, '/app')
os.chdir('/app')

from datetime import datetime, timezone, timedelta

print("=== Debug Fetch Test ===")
now = datetime.now(timezone.utc)
print(f"Current UTC time: {now}")

# Calculate what provider would use for start
limit = 5
tf_seconds = 300  # 5 minutes
use_start = now - timedelta(seconds=limit * tf_seconds * 4)
print(f"Provider use_start would be: {use_start}")
print(f"Difference: {(now - use_start).total_seconds()} seconds = {(now - use_start).total_seconds()/60} minutes")

# Convert to ms
start_ms = int(use_start.timestamp() * 1000)
end_ms = int(now.timestamp() * 1000)
print(f"Start ms: {start_ms}, End ms: {end_ms}")

# Test raw API call with those exact params
api_key = os.getenv('MASSIVE_API_KEY', '')
url = f'https://api.polygon.io/v2/aggs/ticker/C:EURUSD/range/5/minute/{start_ms}/{end_ms}'
resp = requests.get(url, params={'apiKey': api_key, 'limit': 5, 'sort': 'desc'})
print(f"\nAPI with ms timestamps status: {resp.status_code}")
data = resp.json()
print(f"Results count: {data.get('resultsCount', 0)}")
if data.get('results'):
    print(f"First result t: {data['results'][0].get('t')}")
    first_t = data['results'][0].get('t')
    print(f"First result datetime: {datetime.fromtimestamp(first_t/1000, tz=timezone.utc)}")

# Test with date strings (like working curl)
print("\n=== Test with date strings ===")
url2 = 'https://api.polygon.io/v2/aggs/ticker/C:EURUSD/range/5/minute/2026-01-13/2026-01-13'
resp2 = requests.get(url2, params={'apiKey': api_key, 'limit': 5})
data2 = resp2.json()
print(f"Results count with dates: {data2.get('resultsCount', 0)}")

print("\n=== Done ===")


