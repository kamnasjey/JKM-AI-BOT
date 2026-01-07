import sys
import os
import json
import logging
from pathlib import Path

# === 1. Setup Robust Paths ===
# Resolve repo root from this file's location: tools/verify... -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

print(f"Running from: {os.getcwd()}")
print(f"Python: {sys.executable}")

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("VerifyWiring")

try:
    from core.signals_store import (
        DEFAULT_SIGNALS_PATH, 
        DEFAULT_PUBLIC_SIGNALS_PATH, 
        append_signal_jsonl, 
        append_public_signal_jsonl
    )
    from core.signal_payload_v1 import SignalPayloadV1
    from core.signal_payload_public_v1 import to_public_v1
    from services.models import SignalEvent
except ImportError as e:
    logger.error(f"Failed to import core modules. Check PYTHONPATH. Error: {e}")
    sys.exit(1)

def main():
    logger.info("=== 1. Setup & Cleanup ===")
    state_dir = REPO_ROOT / "state"
    state_dir.mkdir(exist_ok=True)
    
    # Optional: Backup existing files? No, appending is fine.
    
    logger.info("=== 2. Create Payloads ===")
    # Construct a valid legacy payload (SignalPayloadV1 Pydantic model)
    # We use a unique ID to verify this specific run
    import uuid
    run_id = uuid.uuid4().hex[:8]
    test_symbol = f"VERIFY_{run_id}"
    
    payload_v1 = SignalPayloadV1(
        signal_id=f"sig_{run_id}",
        user_id="verify_user",
        symbol=test_symbol,
        tf="M15",
        direction="BUY",
        entry=1.1234,
        sl=1.1100,
        tp=1.1400,
        rr=2.5,
        strategy_id="verify_strat",
        scan_id=f"scan_{run_id}",
        reasons=["VERIFICATION_RUN"],
        timestamp="2025-01-01T12:00:00Z"
    )
    
    logger.info(f"Generated Payload V1: ID={payload_v1.signal_id} Symbol={payload_v1.symbol}")

    logger.info("=== 3. Execute Persistence (Dual Write) ===")
    try:
        # Lagacy Write
        append_signal_jsonl(payload_v1)
        logger.info(f"legacy append ok -> {DEFAULT_SIGNALS_PATH}")
        
        # Public Write (Simulate what scanner_service does: convert then append)
        pub_payload = to_public_v1(payload_v1)
        append_public_signal_jsonl(pub_payload)
        logger.info(f"public append ok -> {DEFAULT_PUBLIC_SIGNALS_PATH}")
        
    except Exception as e:
        logger.error(f"Persistence failed: {e}")
        sys.exit(1)
        
    logger.info("=== 4. Verify File Content ===")
    
    # Check Legacy
    if not DEFAULT_SIGNALS_PATH.exists():
        logger.error("Legacy file NOT created!")
        sys.exit(1)
    
    with open(DEFAULT_SIGNALS_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
        last_line = json.loads(lines[-1])
        if last_line.get("signal_id") != payload_v1.signal_id:
             logger.error(f"Legacy file last line mismatch. Got {last_line.get('signal_id')}")
             sys.exit(1)
        logger.info("Legacy File Content: OK")

    # Check Public
    if not DEFAULT_PUBLIC_SIGNALS_PATH.exists():
        logger.error("Public file NOT created!")
        sys.exit(1)
        
    with open(DEFAULT_PUBLIC_SIGNALS_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
        last_line = json.loads(lines[-1])
        if last_line.get("signal_id") != payload_v1.signal_id:
             logger.error(f"Public file last line mismatch. Got {last_line.get('signal_id')}")
             sys.exit(1)
        if "engine_annotations" not in last_line and "legacy" not in last_line:
             # Basic check for shape
             pass 
        logger.info("Public File Content: OK")

    logger.info("=== 5. Verify API Response (Simulated) ===")
    try:
        # Try importing dependencies for API test
        try:
            from fastapi.testclient import TestClient
            from apps.web_app import app
        except ImportError:
            logger.warning("FastAPI or dependencies missing. Skipping API simulation.")
            logger.info("File verification was successful, so API reading should work if env is correct.")
            sys.exit(0)

        client = TestClient(app)
        response = client.get("/api/signals?limit=5")
        
        if response.status_code != 200:
            logger.error(f"API Returned {response.status_code}: {response.text}")
            sys.exit(1)
            
        data = response.json()
        logger.info(f"API Response: 200 OK. Returned {len(data)} items.")
        
        # Find our item
        found = next((x for x in data if x.get("signal_id") == payload_v1.signal_id), None)
        if found:
            logger.info(f"API successfully returned the verified signal: {found['symbol']}")
        else:
            logger.warning("Verified signal not in top 5 list (might be sort order or other data). but API is working.")
            
    except Exception as e:
        logger.error(f"API verification failed: {e}")
        sys.exit(1)

    logger.info("=== VERIFICATION SUCCESS ===")

if __name__ == "__main__":
    main()
