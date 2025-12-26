from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from core.feature_flags import FeatureFlags
from engines.detectors.base import BaseDetector, DetectorResult
from engines.detectors.registry import detector_registry
from engines.detectors.runner import safe_detect


def test_feature_flags_default_stable_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FEATURE_FLAGS", raising=False)
    monkeypatch.delenv("DISABLE_FEATURE_FLAGS", raising=False)
    monkeypatch.delenv("CANARY_MODE", raising=False)
    monkeypatch.delenv("SHADOW_ALL_DETECTORS", raising=False)

    ff = FeatureFlags.from_sources(config=None)
    assert ff.is_enabled("anything") is False
    assert ff.canary_mode is False
    assert ff.shadow_all_detectors is False


def test_safe_detect_never_raises_on_detector_exception(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid writing into repo state/
    monkeypatch.chdir(tmp_path)

    class BoomDetector(BaseDetector):
        name = "qa_boom_detector"

        def detect(self, candles, primitives, context=None) -> DetectorResult:
            raise RuntimeError("boom")

    d = BoomDetector({"enabled": True})
    r, ms = safe_detect(d, candles=[], primitives=None, context={"pair": "X"}, scan_id="S", flags=FeatureFlags.from_sources())

    assert isinstance(ms, float)
    assert r.match is False
    assert r.hit is False
    assert "DETECTOR_RUNTIME_ERROR" in (r.reason_codes or [])
    assert isinstance(r.evidence_dict, dict)


def test_detector_result_contract_fields_are_consistent() -> None:
    r = DetectorResult(detector_name="x", match=True, reasons=["OK"], evidence_dict={"a": 1})
    assert r.hit is True
    assert r.match is True
    assert isinstance(r.evidence_payload, dict)


def test_registry_run_all_is_nonfatal_on_exception(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    class HitDetector(BaseDetector):
        name = "qa_hit_detector"

        def detect(self, candles, primitives, context=None) -> DetectorResult:
            return DetectorResult(detector_name=self.name, match=True, direction="BUY", confidence=0.9)

    class FailDetector(BaseDetector):
        name = "qa_fail_detector"

        def detect(self, candles, primitives, context=None) -> DetectorResult:
            raise ValueError("fail")

    ok = HitDetector({"enabled": True})
    bad = FailDetector({"enabled": True})

    out = detector_registry.run_all([ok, bad], candles=[], primitives=None, context={"pair": "X"})
    assert isinstance(out, list)
    assert any(getattr(x, "detector_name", "") == "qa_hit_detector" for x in out)
    # Failure detector should not blow up the run
