"""tools.demo_step4_5_logs

Runs 3 deterministic indicator-free scans (via runtime patching) and prints
exactly three structured log lines:
- PAIR_OK (with strategy_id, score, top_hits)
- PAIR_NONE reason=NO_HITS (with strategy_id)
- PAIR_NONE reason=NO_DETECTORS_FOR_REGIME (with detectors_total, regime)

This is only for demonstrating log output format.

Usage:
  .venv/Scripts/python.exe tools/demo_step4_5_logs.py
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
    logger = logging.getLogger("Step4_5_Demo")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers[:] = [handler]
    logger.propagate = False
    return logger


def run_case(*, case: str):
    import core.primitives as primitives_mod
    from core.primitives import StructureResult
    from core.types import Regime

    if case == "OK_RANGE":
        forced_regime = Regime.RANGE.value
    elif case == "NO_HITS_RANGE":
        forced_regime = Regime.RANGE.value
    elif case == "NO_DETECTORS_TREND":
        forced_regime = Regime.TREND_BULL.value
    else:
        raise ValueError(case)

    def fake_analyze_structure(*args, **kwargs):
        return StructureResult(
            ok=True,
            regime=forced_regime,
            evidence={"hh": 2, "hl": 2, "lh": 1, "ll": 1},
        )

    def fake_compute_primitives(*args, **kwargs):
        return SimpleNamespace(structure_trend=None)

    primitives_mod.analyze_structure = fake_analyze_structure  # type: ignore[assignment]
    primitives_mod.compute_primitives = fake_compute_primitives  # type: ignore[assignment]

    import engines.detectors as det_mod

    class FakeDetector:
        def __init__(self, name: str, *, supported_regimes):
            self._name = name
            self.meta = SimpleNamespace(supported_regimes=set(supported_regimes))

        def is_enabled(self):
            return True

        def get_name(self):
            return self._name

        def get_family(self):
            return "range"

        def detect(self, candles, primitives, context):
            return SimpleNamespace(match=False)

    class HitDetector(FakeDetector):
        def detect(self, candles, primitives, context):
            last = candles[-1].close
            return SimpleNamespace(
                match=True,
                detector_name=self._name,
                direction="BUY",
                score_contrib=0.80,
                rr=2.0,
                reasons=["demo_hit"],
                evidence_dict={"note": "demo"},
                entry=float(last),
                sl=float(last - 0.01),
                tp=float(last + 0.02),
            )

    def fake_load_from_profile(p):
        det_cfg = (p or {}).get("detectors") or {}
        names = [str(k) for k in det_cfg.keys()]
        if not names:
            return []
        if case == "OK_RANGE":
            return [HitDetector(names[0], supported_regimes={Regime.RANGE.value, Regime.CHOP.value})]
        if case == "NO_HITS_RANGE":
            return [FakeDetector(names[0], supported_regimes={Regime.RANGE.value, Regime.CHOP.value})]
        if case == "NO_DETECTORS_TREND":
            return [FakeDetector(names[0], supported_regimes={Regime.RANGE.value, Regime.CHOP.value})]
        return []

    det_mod.detector_registry.load_from_profile = fake_load_from_profile  # type: ignore[assignment]

    profile = {
        "engine_version": "indicator_free_v1",
        "trend_tf": "H4",
        "entry_tf": "M15",
        "strategies": [
            {
                "strategy_id": f"demo_{case.lower()}",
                "enabled": True,
                "min_score": 0.50,
                "min_rr": 1.20,
                "allowed_regimes": ["RANGE"] if forced_regime == Regime.RANGE.value else ["TREND_BULL"],
                "detectors": ["range_box_edge"],
                "detector_weights": {"range_box_edge": 1.0},
                "family_weights": {"range": 1.0},
                "conflict_epsilon": 0.15,
                "confluence_bonus_per_family": 0.25,
            }
        ],
    }

    trend_c = make_candles(200, start_price=1.0, step=0.00005)
    entry_c = make_candles(120, start_price=1.1, step=0.00005)

    return scan_pair_cached_indicator_free("EURUSD", profile, trend_c, entry_c)


def main() -> None:
    logger = _logger()
    scan_id = make_scan_id()

    r1 = run_case(case="OK_RANGE")
    dbg1 = r1.debug if isinstance(r1.debug, dict) else {}
    log_kv(
        logger,
        "PAIR_OK",
        scan_id=scan_id,
        symbol="EURUSD",
        strategy_id=str(dbg1.get("strategy_id")),
        score=(f"{float(dbg1.get('score')):.2f}" if dbg1.get("score") is not None else None),
        top_hits=(
            ",".join(list(dbg1.get("detectors_hit") or [])[:4])
            if isinstance(dbg1.get("detectors_hit"), list)
            else None
        ),
    )

    r2 = run_case(case="NO_HITS_RANGE")
    dbg2 = r2.debug if isinstance(r2.debug, dict) else {}
    log_kv(
        logger,
        "PAIR_NONE",
        scan_id=scan_id,
        symbol="EURUSD",
        strategy_id=str(dbg2.get("strategy_id")),
        reason=normalize_pair_none_reason(r2.reasons),
    )

    r3 = run_case(case="NO_DETECTORS_TREND")
    dbg3 = r3.debug if isinstance(r3.debug, dict) else {}
    log_kv(
        logger,
        "PAIR_NONE",
        scan_id=scan_id,
        symbol="EURUSD",
        strategy_id=str(dbg3.get("strategy_id")),
        reason=normalize_pair_none_reason(r3.reasons),
        detectors_total=dbg3.get("detectors_total"),
        regime=dbg3.get("regime"),
    )


if __name__ == "__main__":
    main()
