import sys
import logging
from pathlib import Path
from core.signals_store import DEFAULT_SIGNALS_PATH, DEFAULT_PUBLIC_SIGNALS_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DebugSignalsHistory")

def main():
    logger.info("=== Debugging Signal History Paths ===")
    
    # 1. Print Paths
    logger.info(f"Legacy Signals Path: {DEFAULT_SIGNALS_PATH}")
    logger.info(f"Public Signals Path: {DEFAULT_PUBLIC_SIGNALS_PATH}")
    
    # 2. Check Directories
    legacy_dir = DEFAULT_SIGNALS_PATH.parent
    public_dir = DEFAULT_PUBLIC_SIGNALS_PATH.parent
    
    logger.info(f"State Directory (Legacy Parent): {legacy_dir}")
    logger.info(f"State Directory Exists? {legacy_dir.exists()}")
    
    if str(legacy_dir) != str(public_dir):
        logger.info(f"Public Directory: {public_dir}")
        logger.info(f"Public Directory Exists? {public_dir.exists()}")

    # 3. Check Write Permissions (Optional Test Write)
    if len(sys.argv) > 1 and sys.argv[1] == "--write-test":
        logger.info("Attempting test write...")
        try:
            legacy_dir.mkdir(parents=True, exist_ok=True)
            test_file = legacy_dir / "debug_write_test.txt"
            test_file.write_text("ok", encoding="utf-8")
            logger.info(f"Write success: {test_file}")
            test_file.unlink(missing_ok=True)
            logger.info("Test file cleaned up.")
        except Exception as e:
            logger.error(f"Write failed: {e}")
    else:
        logger.info("Skipping write test. Run with --write-test to verify permissions.")

    logger.info("=== Done ===")

if __name__ == "__main__":
    main()
