from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ig_client import IGClient, ig_call_source
from market_data_cache import market_cache
from providers.ig_provider import IGProvider


def _calc_needed_m5(*, days: Optional[int], candle_count: Optional[int]) -> int:
    if candle_count is not None and int(candle_count) > 0:
        return int(candle_count)
    d = int(days or 0)
    if d <= 0:
        d = 14
    return d * 24 * 12  # 288 M5 candles per day


def _coverage_line(symbol: str) -> str:
    m5 = len(market_cache.get_candles(symbol))
    h1 = len(market_cache.get_resampled(symbol, "H1"))
    h4 = len(market_cache.get_resampled(symbol, "H4"))
    d1 = len(market_cache.get_resampled(symbol, "D1"))
    last_ts = market_cache.get_last_timestamp(symbol)
    last_s = last_ts.isoformat() if last_ts is not None else "-"
    return f"{symbol:8s} | M5={m5:5d} | H1={h1:4d} | H4={h4:4d} | D1={d1:4d} | last={last_s}"


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Backfill MarketDataCache with enough M5 candles for HTF analysis")
    p.add_argument("--symbols", default="XAUUSD,EURUSD,BTCUSD", help="Comma-separated symbols")
    p.add_argument("--days", type=int, default=14, help="Days of M5 candles to fetch (default: 14)")
    p.add_argument("--candle-count", type=int, default=0, help="Explicit M5 candle count (overrides --days)")
    p.add_argument("--out", default="data/market_cache.json", help="Output cache json path")
    p.add_argument("--demo", action="store_true", help="Force IG demo mode")
    args = p.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("No symbols provided")
        return 1

    needed = _calc_needed_m5(days=args.days, candle_count=(args.candle_count if args.candle_count > 0 else None))

    print(f"Loading existing cache: {args.out}")
    market_cache.load_json(args.out)

    print(f"Connecting IG (demo={bool(args.demo)})...")
    client = IGClient.from_env(is_demo=bool(args.demo))
    provider = IGProvider(client)

    t_all = time.perf_counter()
    for sym in symbols:
        before = len(market_cache.get_candles(sym))
        print(f"\n=== Backfill {sym} target_m5={needed} (before={before}) ===")

        epic = provider._resolve_epic(sym)
        all_candles = []
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=int(args.days or 14))

        # Chunk by 3 days to avoid IG per-request limits; page within each chunk.
        chunk_end = now
        chunk_days = 3
        page_size = 1000

        with ig_call_source("backfill"):
            while chunk_end > start and len(all_candles) < needed:
                chunk_start = max(start, chunk_end - timedelta(days=chunk_days))
                page = 1
                chunk_total = 0

                while len(all_candles) < needed:
                    try:
                        batch = client.fetch_candles_range(
                            epic,
                            resolution="MINUTE_5",
                            start=chunk_start,
                            end=chunk_end,
                            page_size=page_size,
                            page_number=page,
                        )
                    except Exception as e:
                        # Range endpoint may be forbidden/unavailable depending on IG account.
                        print(f"WARN: range fetch failed ({sym} p{page}) -> {e}")
                        batch = []

                    if not batch:
                        break

                    all_candles.extend(batch)
                    chunk_total += len(batch)

                    # Stop if this page returned less than page_size
                    if len(batch) < page_size:
                        break
                    page += 1
                    if page > 50:
                        # Guardrail against infinite paging
                        break

                print(
                    f"{sym}: chunk {chunk_start.date().isoformat()}..{chunk_end.date().isoformat()} pages={page} got={chunk_total} total={len(all_candles)}"
                )

                chunk_end = chunk_start

        # If range fetch produced nothing, try the legacy latest-N call.
        if not all_candles:
            with ig_call_source("backfill"):
                try:
                    all_candles = provider.get_candles(sym, timeframe="m5", limit=needed)
                except Exception as e:
                    print(f"ERROR: latest-N fetch failed for {sym} -> {e}")
                    all_candles = []

        got = len(all_candles)
        if not all_candles:
            print(f"{sym}: got 0 candles (check EPIC mapping / IG permissions)")
            continue

        # Merge/dedupe by timestamp via MarketDataCache
        market_cache.upsert_candles(sym, all_candles)
        after = len(market_cache.get_candles(sym))

        print(f"{sym}: fetched={got} merged_after={after}")
        print(_coverage_line(sym))

        if got < needed:
            print(f"WARN: IG returned {got} < requested {needed}. IG max may be lower; consider increasing days gradually.")

    print("\nSaving cache...")
    market_cache.save_json(args.out)

    dt = (time.perf_counter() - t_all) * 1000.0
    now = datetime.now(timezone.utc).isoformat()
    print(f"Done at {now} | total_ms={dt:.0f}")

    print("\n=== Coverage summary ===")
    for sym in symbols:
        if market_cache.get_candles(sym):
            print(_coverage_line(sym))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
