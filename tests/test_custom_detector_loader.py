from __future__ import annotations


def test_custom_detector_loader_nonfatal_and_registers(tmp_path):
    from detectors.custom_loader import load_custom_detectors
    from engines.detectors import detector_registry

    custom_dir = tmp_path / "custom"
    custom_dir.mkdir(parents=True, exist_ok=True)

    (custom_dir / "ok_detector.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "from typing import Any, Dict, List, Optional",
                "from engines.detectors.registry import register_detector",
                "from engines.detectors.base import BaseDetector, DetectorResult",
                "from engine_blocks import Candle",
                "from core.primitives import PrimitiveResults",
                "",
                "@register_detector",
                "class CustomTestDetector(BaseDetector):",
                "    name = 'custom_test_detector_1'",
                "    description = 'test'",
                "",
                "    def detect(self, candles: List[Candle], primitives: PrimitiveResults, context: Optional[Dict[str, Any]] = None) -> DetectorResult:",
                "        return DetectorResult(detector_name=self.name, match=False)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (custom_dir / "bad_detector.py").write_text(
        "raise RuntimeError('boom')\n",
        encoding="utf-8",
    )

    res = load_custom_detectors(str(custom_dir))
    assert res.loaded_count == 1
    assert res.failed_count == 1

    assert detector_registry.get_detector_class("custom_test_detector_1") is not None
