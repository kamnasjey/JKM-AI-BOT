from __future__ import annotations

import io
import logging

import pytest

from core.ops import log_startup_banner


def _capture_banner(*, strict: str | None = None) -> str:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("test_startup_banner_detectors")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False
    logger.addHandler(handler)

    if strict is not None:
        import os

        os.environ["STRICT_STARTUP"] = strict

    log_startup_banner(logger, presets_dir="config/presets", notify_mode="all", provider="simulation")
    return stream.getvalue()


def test_banner_detectors_count_nonzero_with_default_packs(monkeypatch) -> None:
    # Ensure strict startup is off for this test.
    import os

    monkeypatch.setenv("STRICT_STARTUP", "0")
    out = _capture_banner(strict=None)

    assert "STARTUP_BANNER" in out
    # Contract: detectors count must be > 0 in a healthy default runtime.
    # Parse from log line.
    for line in out.splitlines():
        if "STARTUP_BANNER" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        det_parts = [p for p in parts if p.startswith("detectors=")]
        assert det_parts, out
        det_n = int(det_parts[0].split("=", 1)[1])
        assert det_n > 0, out
        return
    raise AssertionError(out)


def test_strict_startup_raises_when_no_detectors(monkeypatch) -> None:
    # Force count==0 and ensure loader doesn't populate.
    from engines.detectors import registry as reg

    monkeypatch.setenv("STRICT_STARTUP", "1")
    monkeypatch.setattr(reg, "ensure_registry_loaded", lambda **_: None)
    monkeypatch.setattr(reg.detector_registry, "count", lambda: 0)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("test_startup_banner_strict")
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False
    logger.addHandler(handler)

    with pytest.raises(RuntimeError):
        log_startup_banner(logger, presets_dir="config/presets", notify_mode="all", provider="simulation")

    out = stream.getvalue()
    assert "STARTUP_WARN" in out
    assert "code=NO_DETECTORS_LOADED" in out
