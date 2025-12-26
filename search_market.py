import sys
import codecs
from ig_client import IGClient

if sys.stdout.encoding != 'utf-8':
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

# logging.basicConfig(level=logging.DEBUG)

def search_market(search_term):
    print(f"Searching for '{search_term}'...")
    ig = IGClient.from_env()
    ig.login()
    
    # Try V1 search
    url = f"{ig.base_url}/markets"
    headers = ig._auth_headers(version="1")
    params = {"searchTerm": search_term}
    
    print(f"GET {url} {params}")
    resp = ig.session.get(url, headers=headers, params=params)
    
    if resp.status_code != 200:
        print(f"Error: {resp.status_code}")
        print(f"Body: {resp.text}")
        return

    data = resp.json()
    markets = data.get("markets", [])
    
    if not markets:
        print("No markets found.")
        return
        
    for m in markets:
        epic = m.get("epic")
        instrument = m.get("instrumentName")
        status = m.get("marketStatus")
        expiry = m.get("expiry")
        print(f"Found: {epic} | {instrument} | {expiry} | Status: {status}")

if __name__ == "__main__":
    term = sys.argv[1] if len(sys.argv) > 1 else "Gold"
    search_market(term)
