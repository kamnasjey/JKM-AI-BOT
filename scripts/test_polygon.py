#!/usr/bin/env python3
import requests
import os

key = os.getenv('MASSIVE_API_KEY')
print(f"API Key: {key[:5]}..." if key else "No API key")

url = 'https://api.polygon.io/v2/aggs/ticker/C:EURUSD/range/5/minute/2026-01-12/2026-01-12'
resp = requests.get(url, params={'apiKey': key, 'limit': 5})
print(f'Status: {resp.status_code}')
data = resp.json()
print(f'ResultsCount: {data.get("resultsCount", 0)}')
if data.get('results'):
    print(f'First result: {data["results"][0]}')
else:
    print(f'Response: {data}')
