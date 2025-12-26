from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.primitives import compute_primitives
from engines.detectors.base import SelfTestCase
from engines.detectors.registry import detector_registry, ensure_registry_loaded
from tests.fixtures.candles import load_candles


def _run_case(det_name: str, case: SelfTestCase) -> None:
    candles = load_candles(case.fixture_id)
    primitives = compute_primitives(
        trend_candles=candles,
        entry_candles=candles,
        trend_direction="flat",
        config={},
    )

    cfg: Dict[str, Any] = {"enabled": True}
    if case.config_overrides:
        cfg.update(dict(case.config_overrides))

    det = detector_registry.create_detector(det_name, cfg)
    assert det is not None, f"Failed to create detector: {det_name}"

    context: Dict[str, Any] = {
        "pair": "TEST",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "user_profile": {},
        "strategy_id": "qa",
    }

    res = det.detect(candles, primitives, context)

    assert bool(res.match) == bool(case.expect_match), (
        f"{det_name} fixture={case.fixture_id} expected match={case.expect_match} got {res.match}"
    )

    if case.expect_match and case.expect_direction is not None:
        assert res.direction == case.expect_direction, (
            f"{det_name} fixture={case.fixture_id} expected dir={case.expect_direction} got {res.direction}"
        )


def test_all_detectors_have_hit_and_nohit_selftests() -> None:
    """QA gate: every registered detector must declare deterministic selftests."""
    ensure_registry_loaded(logger=None, custom_dir="detectors/custom")
    names = detector_registry.list_detectors()
    assert names, "No detectors registered"

    missing: List[str] = []
    missing_hit: List[str] = []
    missing_nohit: List[str] = []

    for name in names:
        cls = detector_registry.get_detector_class(name)
        meta = getattr(cls, "meta", None) if cls is not None else None
        selftests: Optional[List[SelfTestCase]] = getattr(meta, "selftests", None) if meta is not None else None

        if not selftests:
            missing.append(name)
            continue

        has_hit = any(bool(tc.expect_match) for tc in selftests)
        has_nohit = any(not bool(tc.expect_match) for tc in selftests)
        if not has_hit:
            missing_hit.append(name)
        if not has_nohit:
            missing_nohit.append(name)

    assert not missing, f"Detectors missing selftests: {missing}"
    assert not missing_hit, f"Detectors missing HIT selftest: {missing_hit}"
    assert not missing_nohit, f"Detectors missing NO_HIT selftest: {missing_nohit}"

def test_detector_selftests_run() -> None:
    """Execute every declared selftest; failures show fixture + detector."""
    ensure_registry_loaded(logger=None, custom_dir="detectors/custom")
    names = detector_registry.list_detectors()
    assert names, "No detectors registered"

    for det_name in names:
        cls = detector_registry.get_detector_class(det_name)
        assert cls is not None

        meta = getattr(cls, "meta", None)
        selftests: List[SelfTestCase] = list(getattr(meta, "selftests", []) or [])
        assert selftests, f"No selftests for {det_name}"

        for tc in selftests:
            _run_case(det_name, tc)
