import logging
import sys
import codecs
import requests
from ig_client import IGClient

# Force UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

logging.basicConfig(level=logging.INFO)

def search_markets(client, query):
    url = f"{client.base_url}/markets"
    params = {"searchTerm": query}
    headers = client._auth_headers(version="1") # Search is often v1
    
    print(f"Searching for '{query}'...")
    try:
        resp = client.session.get(url, params=params, headers=headers)
        if resp.status_code == 403:
             print("SEARCH 403: Account likely restricted or wrong scope.")
             return []
        resp.raise_for_status()
        data = resp.json()
        return data.get("markets", [])
    except Exception as e:
        print(f"Search Failed: {e}")
        try:
            print(resp.text)
        except: pass
        return []

def main():
    print("Logging in to IG (demo/live based on env)...")
    try:
        ig = IGClient.from_env()
        # Note: from_env calls login() internally
    except Exception as e:
        print(f"Login Failed: {e}")
        return

    query = "USDJPY"
    markets = search_markets(ig, query)
    
    if not markets:
        print("No markets found via Search API.")
    print(f"\nFound {len(markets)} markets for {query}:")
    for m in markets:
        epic = m.get('epic')
        print(f" - EPIC: {epic} | Status: {m.get('marketStatus')} | Name: {m.get('instrumentName')} | Type: {m.get('instrumentType')}")
        
    print("\n--- Verifying Candle Access for top matches ---")
    for m in markets[:3]: # Check top 3
        epic = m.get('epic')
        if not epic: continue
        print(f"Testing Candle Fetch for {epic} ...", end=" ")
        try:
            # Try specific params that are usually safe
            candles = ig.get_candles(epic, resolution="MINUTE_15", max_points=5)
            n = len(candles) if candles else 0
            if n > 0:
                print(f"[SUCCESS] Got {n} candles. Last: {candles[-1]['close']}")
            else:
                print(f"[OK] Got 0 candles (no error).")
        except Exception as e:
            print(f"[FAIL] {e}")

    # Also try specifically XAUUSD just in case
    print("\nChecking Gold (XAUUSD)...")
    markets_gold = search_markets(ig, "Gold")
    for m in markets_gold:
         print(f" - EPIC: {m.get('epic')} | Name: {m.get('instrumentName')}")

if __name__ == "__main__":
    main()
