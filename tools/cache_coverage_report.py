from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from market_data_cache import market_cache


def _tf_count(symbol: str, tf: str) -> int:
    try:
        candles = market_cache.get_resampled(symbol, tf)
        return len(candles)
    except Exception:
        return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Report cache coverage for M5->H1/H4/D1")
    p.add_argument("--cache", default="data/market_cache.json", help="Path to cache JSON")
    p.add_argument("--symbols", default="", help="Comma-separated symbols (default: all in cache)")
    args = p.parse_args(argv)

    market_cache.load_json(args.cache)

    if args.symbols.strip():
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = sorted(market_cache.get_all_symbols())

    if not symbols:
        print("No symbols found in cache")
        return 1

    print(f"Cache: {args.cache}")
    for sym in symbols:
        m5 = market_cache.get_candles(sym)
        h1 = _tf_count(sym, "H1")
        h4 = _tf_count(sym, "H4")
        d1 = _tf_count(sym, "D1")
        last_ts = market_cache.get_last_timestamp(sym)
        last_s = last_ts.isoformat() if last_ts is not None else "-"
        print(f"{sym:8s} | M5={len(m5):5d} | H1={h1:4d} | H4={h4:4d} | D1={d1:4d} | last={last_s}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
