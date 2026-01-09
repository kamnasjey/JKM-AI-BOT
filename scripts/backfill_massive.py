from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

# When executed as `python scripts/backfill_massive.py`, Python sets sys.path[0]
# to `/app/scripts` and won't see `/app` for top-level imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_providers.factory import create_provider
from data_providers.models import Candle, candles_to_cache_dicts
from data_providers.massive_provider import to_massive_ticker
from core.marketdata_store import append as store_append
from core.ingest_debug import log_ingest_event

import logging

logger = logging.getLogger("backfill_massive")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _load_default_symbols() -> List[str]:
    # Prefer a dedicated config file if present.
    cfg = Path("config/massive_symbols.json")
    if cfg.exists():
        try:
            raw = json.loads(cfg.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                out = [str(x).upper().strip() for x in raw if isinstance(x, str) and str(x).strip()]
                out = sorted(list(dict.fromkeys(out)))
                if out:
                    return out
        except Exception:
            pass

    # Fallback: known canonical symbols in instruments catalog.
    cat = Path("data_providers/instruments.json")
    if cat.exists():
        try:
            raw = json.loads(cat.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                out = [str(k).upper().strip() for k in raw.keys() if isinstance(k, str) and str(k).strip()]
                out = sorted(list(dict.fromkeys(out)))
                if out:
                    return out
        except Exception:
            pass

    # Hard default per spec (15 instruments)
    return [
        "EURUSD",
        "USDJPY",
        "GBPUSD",
        "AUDUSD",
        "USDCAD",
        "USDCHF",
        "NZDUSD",
        "EURJPY",
        "GBPJPY",
        "EURGBP",
        "AUDJPY",
        "EURAUD",
        "EURCHF",
        "XAUUSD",
        "BTCUSD",
    ]


def _canon_tf(timeframe: str) -> str:
    tf = str(timeframe or "").strip().lower()
    if tf in {"5m", "m5", "minute_5"}:
        return "m5"
    return tf or "m5"


def _chunk_ranges(start: datetime, end: datetime, *, chunk_days: int) -> Iterable[tuple[datetime, datetime]]:
    cur = start
    step = timedelta(days=max(1, int(chunk_days)))
    while cur < end:
        nxt = min(end, cur + step)
        yield (cur, nxt)
        cur = nxt


def run_backfill(
    *,
    symbols: List[str],
    timeframe: str,
    years: int,
    days: Optional[int],
    chunk_days: int,
    validate_tickers: bool,
) -> int:
    provider = create_provider(name="massive")

    end = datetime.now(timezone.utc)
    if days is not None:
        start = end - timedelta(days=int(days))
    else:
        start = end - timedelta(days=int(years) * 365)

    tf = _canon_tf(timeframe)

    logger.info(
        "Backfill start provider=%s symbols=%d tf=%s years=%d chunk_days=%d",
        getattr(provider, "name", "unknown"),
        len(symbols),
        tf,
        years,
        chunk_days,
    )

    total_written = 0

    for sym in symbols:
        sym = str(sym).upper().strip()
        if not sym:
            continue

        if validate_tickers and hasattr(provider, "validate_ticker_exists"):
            try:
                ok = provider.validate_ticker_exists(to_massive_ticker(sym))
                if ok is False:
                    logger.warning("Ticker validation failed for %s (check MASSIVE_REF_PATH config)", sym)
            except Exception:
                logger.warning("Ticker validation error for %s (skipping)", sym)

        logger.info("Backfilling %s tf=%s from %s to %s", sym, tf, start.isoformat(), end.isoformat())
        for (a, b) in _chunk_ranges(start, end, chunk_days=chunk_days):
            t0 = time.perf_counter()
            # conservative limit estimate for 5m candles
            est = int((b - a).total_seconds() / 300) + 20
            candles: List[Candle] = provider.fetch_candles(
                sym,
                timeframe=str(tf),
                max_count=est,
                limit=est,
                since_ts=a,
                until_ts=b,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0

            cache_dicts = candles_to_cache_dicts(candles) if candles else []
            written, path = store_append(sym, tf, cache_dicts)
            total_written += int(written)

            massive_ticker: Optional[str] = None
            try:
                massive_ticker = to_massive_ticker(sym)
            except Exception:
                massive_ticker = None

            log_ingest_event(
                logger,
                "backfill_chunk",
                provider=getattr(provider, "name", "unknown"),
                symbol=sym,
                timeframe=str(tf),
                candles_count=int(written),
                requested_start=a.isoformat(),
                requested_end=b.isoformat(),
                persist_path=str(path),
                duration_ms=dt_ms,
                extra={
                    "internalSymbol": sym,
                    "massiveTicker": massive_ticker,
                    "fetchedCandles": int(len(candles or [])),
                },
            )

            logger.info(
                "chunk %s %s..%s fetched=%d wrote=%d ms=%.1f",
                sym,
                a.date().isoformat(),
                b.date().isoformat(),
                len(candles or []),
                int(written),
                dt_ms,
            )

    logger.info("Backfill complete total_written=%d", total_written)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill Massive OHLC into state/marketdata")
    ap.add_argument("--symbols", nargs="*", default=None, help="Symbols (default from config/massive_symbols.json)")
    ap.add_argument("--timeframe", default="5m", help="Timeframe, e.g. 5m")
    ap.add_argument("--years", type=int, default=2, help="How many years to backfill")
    ap.add_argument("--days", type=int, default=None, help="Override: backfill last N days")
    ap.add_argument("--chunk-days", type=int, default=7, help="Days per request chunk")
    ap.add_argument("--validate-tickers", action="store_true", help="Validate Massive tickers via ref endpoint (best-effort)")
    args = ap.parse_args(argv)

    syms = [s.upper().strip() for s in (args.symbols or []) if isinstance(s, str) and s.strip()]
    if not syms:
        syms = _load_default_symbols()

    return run_backfill(
        symbols=syms,
        timeframe=str(args.timeframe),
        years=int(args.years),
        days=(int(args.days) if args.days is not None else None),
        chunk_days=int(args.chunk_days),
        validate_tickers=bool(args.validate_tickers),
    )


if __name__ == "__main__":
    raise SystemExit(main())
