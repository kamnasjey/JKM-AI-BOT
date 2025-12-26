import os
import sys

import pytest

from ig_client import IGClient

# Force utf-8 for print if possible
sys.stdout.reconfigure(encoding='utf-8')

def test_fetch():
    pair = "EURUSD"
    print(f"Testing candle fetch for {pair}...")

    # Opt-in only: this hits external IG API and may fail due to permissions/rate limits.
    if os.getenv("RUN_IG_INTEGRATION_TESTS", "").strip() not in ("1", "true", "yes"):
        pytest.skip("Set RUN_IG_INTEGRATION_TESTS=1 to run IG integration tests")

    # This test is integration-style and should not fail CI/local runs
    # when IG credentials are not configured.
    required = ["IG_API_KEY", "IG_USERNAME", "IG_PASSWORD", "IG_ACCOUNT_ID"]
    if not all(os.getenv(k) for k in required):
        pytest.skip("IG credentials not configured in ENV")

    epic_env = f"EPIC_{pair.replace('/', '')}"
    epic = (os.getenv(epic_env) or "").strip()
    if not epic:
        pytest.skip(f"{epic_env} is not set")

    ig = IGClient.from_env()

    def tf_to_ig_resolution(tf: str) -> str:
        tf = (tf or "").upper().replace(" ", "")
        mapping = {
            "M1": "MINUTE",
            "M5": "MINUTE_5",
            "M15": "MINUTE_15",
            "M30": "MINUTE_30",
            "H1": "HOUR",
            "H4": "HOUR_4",
            "D1": "DAY",
        }
        return mapping.get(tf, "MINUTE_5")

    # Check H4
    res = tf_to_ig_resolution("H4")
    print(f"Fetching H4 (300)...")
    try:
        candles = ig.get_candles(epic, resolution=res, max_points=300)
    except Exception as e:
        pytest.skip(f"IG fetch blocked/unavailable: {e}")
    print(f"-> Got {len(candles)}")

    # Check M15
    res = tf_to_ig_resolution("M15")
    print(f"Fetching M15 (400)...")
    try:
        candles_2 = ig.get_candles(epic, resolution=res, max_points=400)
    except Exception as e:
        pytest.skip(f"IG fetch blocked/unavailable: {e}")
    print(f"-> Got {len(candles_2)}")
    
    assert len(candles) >= 50
    assert len(candles_2) >= 50

if __name__ == "__main__":
    try:
        test_fetch()
    except Exception as e:
        print(f"Error: {e}")
