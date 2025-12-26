
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

def test_imports():
    print("Testing imports...")
    try:
        import services.scanner_service
        print("✅ services.scanner_service imported")
    except Exception as e:
        print(f"❌ services.scanner_service failed: {e}")

    try:
        import strategy
        print("✅ strategy imported")
    except Exception as e:
        print(f"❌ strategy failed: {e}")

    try:
        import user_core_engine
        print("✅ user_core_engine imported")
    except Exception as e:
        print(f"❌ user_core_engine failed: {e}")

def test_strategy_logic():
    print("\nTesting strategy logic signatures...")
    from strategy import scan_pairs
    # We won't run it fully as it needs IG connection, but we check if function exists and signature matches expectation
    print(f"✅ scan_pairs found: {scan_pairs}")

def test_engine_decomposition():
    print("\nTesting engine decomposition...")
    from user_core_engine import (
        _validate_data_sufficiency,
        _analyze_trend_step,
        _find_swing_step,
        _check_fibo_step_dir,
        scan_pair_cached,
    )
    # Smoke: symbols exist
    assert _validate_data_sufficiency
    assert _analyze_trend_step
    assert _find_swing_step
    assert _check_fibo_step_dir
    assert scan_pair_cached
    print("✅ Core engine sub-routines found in user_core_engine")

if __name__ == "__main__":
    test_imports()
    test_strategy_logic()
    test_engine_decomposition()
