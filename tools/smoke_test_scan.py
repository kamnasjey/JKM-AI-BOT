"""Smoke test runner for production readiness (Step 5).

Runs N scan cycles over a fixed set of symbols using simulation candles,
and prints the normal SCAN_START / PAIR_* / SCAN_END logs.

Usage:
  # 5.1 Dry-run (Telegram OFF)
  python tools/smoke_test_scan.py --symbols XAUUSD EURUSD BTCUSD --cycles 3 --notify-mode off

  # 5.2 Telegram ON (admin only)
  # Requires TELEGRAM_BOT_TOKEN and a valid ADMIN_CHAT_ID (or DEFAULT_CHAT_ID/ADMIN_USER_ID fallback)
  python tools/smoke_test_scan.py --symbols XAUUSD EURUSD BTCUSD --cycles 3 --notify-mode admin_only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure repo-root is on sys.path when running from tools/.
REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from market_data_cache import market_cache
from providers.simulation_provider import SimulationProvider

import scanner_service as scanner_mod


def _build_smoke_users(symbols: List[str]) -> List[Dict[str, Any]]:
    # Minimal profile fields required by ScannerService._scan_for_user
    min_rr = float(getattr(_ARGS, "min_rr", 1.2) or 1.2)
    require_clear_trend = str(getattr(_ARGS, "require_clear_trend", "false") or "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )
    return [
        {
            "user_id": "smoke_admin",
            "name": "Smoke Admin",
            "watch_pairs": symbols,
            # Force indicator-free engine for consistency with your current direction.
            "engine_version": "indicator_free_v1",
            "trend_tf": "H4",
            "entry_tf": "M15",
            "tz_offset_hours": 0,
            # Keep gates permissive for smoke test.
            "min_rr": min_rr,
            "require_clear_trend_for_signal": require_clear_trend,
            # Range-friendly detectors first (fastest way to get PAIR_OK).
            "detectors": {
                "structure_trend": {"enabled": True},
                "sr_bounce": {"enabled": True},
                "fakeout_trap": {"enabled": True},
                "range_box_edge": {"enabled": True},
            },
            "min_score": 0.0,
            "max_signals_per_day_per_symbol": 999,
            "conflict_policy": "skip",
            "cooldown_minutes": 0,
        }
    ]


def _seed_cache(symbols: List[str], *, m5_bars: int) -> None:
    provider = SimulationProvider()
    for sym in symbols:
        candles = provider.get_candles(sym, timeframe="m5", limit=m5_bars)
        if candles:
            market_cache.upsert_candles(sym, candles)


async def _run_cycles(cycles: int) -> None:
    svc = scanner_mod.ScannerService()

    # Monkeypatch list_users used inside scanner_service module.
    symbols = list(_ARGS.symbols)
    smoke_users = _build_smoke_users(symbols)
    scanner_mod.list_users = lambda: smoke_users  # type: ignore[assignment]

    for _ in range(cycles):
        await svc._scan_cycle()  # noqa: SLF001 (intentional smoke test)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", nargs="+", default=["XAUUSD", "EURUSD", "BTCUSD"])
    p.add_argument("--cycles", type=int, default=3)
    p.add_argument("--m5-bars", type=int, default=3000)
    p.add_argument("--notify-mode", choices=["off", "all", "admin_only"], default="off")
    p.add_argument("--min-rr", type=float, default=1.2)
    p.add_argument(
        "--require-clear-trend",
        choices=["true", "false"],
        default="false",
        help="If true, skip signals when structure trend is unclear (RANGE regime).",
    )
    return p.parse_args()


_ARGS = _parse_args()


def main() -> None:
    # Force simulation unless user explicitly overrides.
    os.environ.setdefault("MARKET_DATA_PROVIDER", "simulation")

    # Set notify mode for this run.
    os.environ["NOTIFY_MODE"] = _ARGS.notify_mode

    symbols = [s.strip().upper() for s in _ARGS.symbols if s.strip()]
    _seed_cache(symbols, m5_bars=max(int(_ARGS.m5_bars), 200))

    asyncio.run(_run_cycles(max(int(_ARGS.cycles), 1)))


if __name__ == "__main__":
    main()
