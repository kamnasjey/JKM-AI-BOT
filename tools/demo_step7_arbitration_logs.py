"""tools.demo_step7_arbitration_logs

Step 7 demo:
- Two strategies both produce OK candidates => engine returns ONE final setup.
- Emits a PAIR_OK log line with candidates summary.
- Emits a PAIR_NONE line with candidates=0.

Usage:
  .venv/Scripts/python.exe tools/demo_step7_arbitration_logs.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from engine.utils.logging_utils import log_kv, make_scan_id
from engine.utils.reason_codes import normalize_pair_none_reason

from core.user_core_engine import scan_pair_cached_indicator_free


def make_candles(n: int, *, start_price: float = 1.0, step: float = 0.0001):
    from engine_blocks import Candle

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    out = []
    price = float(start_price)
    for i in range(n):
        t = start + timedelta(minutes=5 * i)
        o = price
        c = price + step
        h = max(o, c) + abs(step) * 0.5
        l = min(o, c) - abs(step) * 0.5
        out.append(Candle(time=t, open=o, high=h, low=l, close=c))
        price = c
    return out


def _logger() -> logging.Logger:
    logger = logging.getLogger("Step7Demo")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers[:] = [handler]
    logger.propagate = False
    return logger


def _patch_regime_range() -> None:
    import core.primitives as primitives_mod
    from core.primitives import StructureResult
    from core.types import Regime

    def fake_analyze_structure(*args, **kwargs):
        return StructureResult(ok=True, regime=Regime.RANGE.value, evidence={"hh": 1, "hl": 1, "lh": 1, "ll": 1})

    def fake_compute_primitives(*args, **kwargs):
        return SimpleNamespace(structure_trend=None)

    primitives_mod.analyze_structure = fake_analyze_structure  # type: ignore[assignment]
    primitives_mod.compute_primitives = fake_compute_primitives  # type: ignore[assignment]


def _patch_registry(*, hit_names: set[str]):
    """Patch registry to return deterministic hits for specific detector names."""

    import engines.detectors as det_mod
    from core.types import Regime

    class FakeDetector:
        def __init__(self, name: str):
            self._name = name
            self.meta = SimpleNamespace(supported_regimes={Regime.RANGE.value, Regime.CHOP.value})

        def is_enabled(self):
            return True

        def get_name(self):
            return self._name

        def get_family(self):
            return "range" if self._name == "range_box_edge" else "sr"

        def detect(self, candles, primitives, context):
            last = candles[-1].close
            if self._name not in hit_names:
                return SimpleNamespace(match=False)

            # Two different scores so we can see arbitration by score.
            score = 1.10 if self._name == "range_box_edge" else 1.05
            rr = 1.50 if self._name == "range_box_edge" else 2.00
            return SimpleNamespace(
                match=True,
                detector_name=self._name,
                direction="BUY",
                score_contrib=float(score),
                rr=float(rr),
                reasons=["demo"],
                evidence_dict={},
                entry=float(last),
                sl=float(last - 0.01),
                tp=float(last + 0.02),
            )

    def fake_load_from_profile(p):
        det_cfg = (p or {}).get("detectors") or {}
        return [FakeDetector(str(k)) for k in det_cfg.keys()]

    det_mod.detector_registry.load_from_profile = fake_load_from_profile  # type: ignore[assignment]


def main() -> None:
    logger = _logger()
    scan_id = make_scan_id()

    _patch_regime_range()

    # --- Case 1: Two candidates -> one winner ---
    _patch_registry(hit_names={"range_box_edge", "sr_bounce"})

    profile_ok = {
        "engine_version": "indicator_free_v1",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "strategies": [
            {
                "strategy_id": "strategyA",
                "enabled": True,
                "priority": 80,
                "min_score": 0.0,
                "min_rr": 0.0,
                "allowed_regimes": ["RANGE"],
                "detectors": ["range_box_edge"],
            },
            {
                "strategy_id": "strategyB",
                "enabled": True,
                "priority": 50,
                "min_score": 0.0,
                "min_rr": 0.0,
                "allowed_regimes": ["RANGE"],
                "detectors": ["sr_bounce"],
            },
        ],
    }

    res_ok = scan_pair_cached_indicator_free("EURUSD", profile_ok, make_candles(60), make_candles(30))
    dbg_ok = res_ok.debug if isinstance(res_ok.debug, dict) else {}

    log_kv(
        logger,
        "PAIR_OK",
        scan_id=scan_id,
        symbol="EURUSD",
        strategy_id=str(dbg_ok.get("strategy_id")),
        winner_strategy_id=str(dbg_ok.get("winner_strategy_id")),
        candidates=dbg_ok.get("candidates"),
        candidates_top=dbg_ok.get("candidates_top"),
    )

    # --- Case 2: No candidates -> PAIR_NONE with candidates=0 ---
    _patch_registry(hit_names=set())

    profile_none = {
        "engine_version": "indicator_free_v1",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "strategies": [
            {
                "strategy_id": "strategyC",
                "enabled": True,
                "priority": 50,
                "min_score": 0.0,
                "min_rr": 0.0,
                "allowed_regimes": ["RANGE"],
                "detectors": ["range_box_edge"],
            }
        ],
    }

    res_none = scan_pair_cached_indicator_free("EURUSD", profile_none, make_candles(60), make_candles(30))
    dbg_none = res_none.debug if isinstance(res_none.debug, dict) else {}

    log_kv(
        logger,
        "PAIR_NONE",
        scan_id=scan_id,
        symbol="EURUSD",
        strategy_id=str(dbg_none.get("strategy_id")),
        reason=normalize_pair_none_reason(res_none.reasons),
        candidates=dbg_none.get("candidates"),
    )


if __name__ == "__main__":
    main()
