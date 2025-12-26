from ig_client import IGClient
from providers.ig_provider import IGProvider
import logging
import sys

# Setup logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("TestIG")

def test_connection():
    try:
        logger.info("1. Initializing IG Client from env...")
        client = IGClient.from_env()
        logger.info("   IG Client initialized.")

        logger.info("2. Initializing IG Provider...")
        provider = IGProvider(client)
        logger.info("   IG Provider initialized.")

        # Search for valid EPICs
        logger.info("3. Searching for 'EURUSD' to find valid EPICs...")
        results = client.search_market("EURUSD")
        
        if results:
            logger.info(f"   SUCCESS! Found {len(results)} markets.")
            for r in results:
                logger.info(f"   - {r.get('epic')} ({r.get('instrumentName')})")
            print("IG_SEARCH: SUCCESS")
        else:
            logger.error("   FAILED. No markets found.")
            print("IG_SEARCH: NO_DATA")
            
    except Exception as e:
        logger.error(f"   ERROR: {e}")
        print(f"IG_SEARCH: ERROR - {e}")

if __name__ == "__main__":
    test_connection()
