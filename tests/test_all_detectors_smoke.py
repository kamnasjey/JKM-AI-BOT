from __future__ import annotations

from typing import Any, Dict

from core.primitives import compute_primitives
from engines.detectors.registry import detector_registry, ensure_registry_loaded
from tests.fixtures.candles import load_candles


def test_all_detectors_smoke_no_crash() -> None:
    """Registry-wide smoke test: instantiate and run detect() once.

    This is intentionally loose: it asserts that detectors do not crash on a
    reasonable fixture and return a DetectorResult.
    """
    ensure_registry_loaded(logger=None, custom_dir="detectors/custom")
    names = detector_registry.list_detectors()
    assert names, "No detectors registered"

    candles = load_candles("smoke")
    primitives = compute_primitives(
        trend_candles=candles,
        entry_candles=candles,
        trend_direction="flat",
        config={},
    )

    context: Dict[str, Any] = {
        "pair": "TEST",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "user_profile": {},
        "strategy_id": "qa",
    }

    for name in names:
        det = detector_registry.create_detector(name, {"enabled": True})
        assert det is not None, f"Failed to create detector: {name}"
        res = det.detect(candles, primitives, context)
        assert getattr(res, "detector_name", None) == name
        assert hasattr(res, "match")
