# data_ingestor_5m.py
import logging
import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from providers.base import MarketDataProvider
from data_providers.base import DataProvider
from data_providers.models import Candle, candles_to_cache_dicts
from market_data_cache import market_cache
from watchlist_union import get_union_watchlist

from core.ingest_debug import log_ingest_event
from core.marketdata_store import append as store_append

from data_providers.massive_provider import to_massive_ticker

import requests

logger = logging.getLogger(__name__)

class DataIngestor:
    def __init__(
        self,
        provider: MarketDataProvider | DataProvider,
        fallback_provider: MarketDataProvider | DataProvider | None = None,
        poll_interval: int = 60,
        warmup: int = 500,
        incremental_limit: int = 5,
        persist_path: str | None = None,
        persist_every_cycles: int = 1,
    ):
        self.provider = provider
        self.fallback_provider = fallback_provider
        self.poll_interval = poll_interval
        self.warmup = warmup
        self.incremental_limit = max(int(incremental_limit), 1)
        self.persist_path = persist_path
        self.persist_every_cycles = max(int(persist_every_cycles), 1)
        self._cycles = 0
        self._running = False
        self._cooldown_until: dict[str, float] = {}

    async def run_forever(self):
        self._running = True
        logger.info("Starting Data Ingestor Service (5m 24/7 loop)...")
        
        while self._running:
            try:
                # 1. Get Symbols
                symbols = get_union_watchlist(max_per_user=5)
                logger.info(f"Ingestor: Refreshing {len(symbols)} symbols: {symbols}")
                
                # 2. Poll Data
                for sym in symbols:
                    await self._fetch_and_cache(sym)
                    # Small sleep to be nice to API
                    await self._sleep_interruptible(0.5)

                # 2.5 Persist cache periodically (best-effort)
                self._cycles += 1
                if self.persist_path and (self._cycles % self.persist_every_cycles == 0):
                    try:
                        market_cache.save_json(self.persist_path)
                    except Exception as e:
                        logger.warning(f"Ingestor: Failed to persist cache: {e}")
                
                # 3. Wait
                logger.info(f"Ingestor: Sleeping {self.poll_interval}s...")
                await self._sleep_interruptible(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Ingestor Loop Criital Error: {e}")
                await self._sleep_interruptible(10)  # Backoff

    async def _sleep_interruptible(self, seconds: float) -> None:
        """Sleep in small increments so stop() can end the loop quickly."""
        if seconds <= 0:
            return

        remaining = float(seconds)
        while self._running and remaining > 0:
            step = 1.0 if remaining > 1.0 else remaining
            await asyncio.sleep(step)
            remaining -= step

    async def _fetch_and_cache(self, symbol: str):
        try:
            now_ts = asyncio.get_running_loop().time()
            cooldown = self._cooldown_until.get(symbol)
            if cooldown and now_ts < cooldown:
                return

            # Check last timestamp in cache
            last_ts = market_cache.get_last_timestamp(symbol)
            limit = self.warmup if not last_ts else self.incremental_limit

            # If we already have a very recent candle, avoid hammering the API.
            # For closed 5m candles, the next one should only appear ~5 minutes later.
            if last_ts is not None:
                now_utc = datetime.now(timezone.utc)
                # small slack for provider delays
                not_before = last_ts + timedelta(minutes=5, seconds=10)
                if now_utc < not_before:
                    return
            
            t_fetch = time.perf_counter()
            requested_end_iso = datetime.now(timezone.utc).isoformat()
            if hasattr(self.provider, "fetch_candles"):
                candles = self.provider.fetch_candles(
                    symbol,
                    timeframe="m5",
                    max_count=limit,
                    since_ts=last_ts,
                )
            else:
                candles = self.provider.get_candles(
                    symbol,
                    timeframe="m5",
                    limit=limit,
                    since_ts=last_ts,
                )
            fetch_ms = (time.perf_counter() - t_fetch) * 1000.0
            
            if candles:
                if isinstance(candles[0], Candle):
                    cache_candles = candles_to_cache_dicts(candles)
                    market_cache.upsert_candles(symbol, cache_candles)
                    logger.info(f"Ingested {len(cache_candles)} candles for {symbol}. Last: {cache_candles[-1]['time']}")

                    # Persist per-symbol marketdata for proof/forensics & backfill reuse.
                    persist_enabled = (os.getenv("MARKETDATA_PERSIST") or "").strip().lower() in ("1", "true", "yes", "on")
                    provider_name = str(getattr(self.provider, "name", "unknown")).upper()
                    if persist_enabled or provider_name == "MASSIVE":
                        massive_ticker: Optional[str] = None
                        if provider_name == "MASSIVE":
                            try:
                                massive_ticker = to_massive_ticker(symbol)
                            except Exception:
                                massive_ticker = None
                        written, path = store_append(symbol, "m5", cache_candles)
                        log_ingest_event(
                            logger,
                            "fetch_and_persist",
                            provider=provider_name,
                            symbol=symbol,
                            timeframe="m5",
                            candles_count=int(written),
                            requested_start=(last_ts.isoformat() if last_ts is not None else None),
                            requested_end=requested_end_iso,
                            persist_path=str(path),
                            duration_ms=fetch_ms,
                            extra={
                                "internalSymbol": str(symbol).upper(),
                                "massiveTicker": massive_ticker,
                                "fetchedCandles": int(len(cache_candles)),
                            },
                        )
                else:
                    market_cache.upsert_candles(symbol, candles)
                    logger.info(f"Ingested {len(candles)} candles for {symbol}. Last: {candles[-1]['time']}")

                    persist_enabled = (os.getenv("MARKETDATA_PERSIST") or "").strip().lower() in ("1", "true", "yes", "on")
                    provider_name = str(getattr(self.provider, "name", "unknown")).upper()
                    if persist_enabled or provider_name == "MASSIVE":
                        massive_ticker: Optional[str] = None
                        if provider_name == "MASSIVE":
                            try:
                                massive_ticker = to_massive_ticker(symbol)
                            except Exception:
                                massive_ticker = None
                        written, path = store_append(symbol, "m5", candles)
                        log_ingest_event(
                            logger,
                            "fetch_and_persist",
                            provider=provider_name,
                            symbol=symbol,
                            timeframe="m5",
                            candles_count=int(written),
                            requested_start=(last_ts.isoformat() if last_ts is not None else None),
                            requested_end=requested_end_iso,
                            persist_path=str(path),
                            duration_ms=fetch_ms,
                            extra={
                                "internalSymbol": str(symbol).upper(),
                                "massiveTicker": massive_ticker,
                                "fetchedCandles": int(len(candles)),
                            },
                        )
            else:
                logger.debug(f"No new candles for {symbol}")

        except Exception as e:
            msg = str(e)
            error_code: Optional[str] = None
            body_short: str = ""

            # If it's an HTTPError, we can sometimes inspect a structured error payload.
            if isinstance(e, requests.exceptions.HTTPError):
                resp = getattr(e, "response", None)
                if resp is not None:
                    try:
                        data = resp.json() if resp.content else {}
                        if isinstance(data, dict):
                            error_code = data.get("errorCode")
                    except Exception:
                        error_code = None
                    try:
                        body_short = (resp.text or "")[:300].replace("\n", " ")
                    except Exception:
                        body_short = ""

            if error_code:
                msg = f"{msg} | errorCode={error_code}"
            if body_short and ("errorCode" in body_short or "exceeded" in body_short):
                msg = f"{msg} | body={body_short}"

            logger.warning(f"Failed to fetch {symbol}: {msg}")

            # Optional: keep the system usable by filling cache from a fallback provider.
            if self.fallback_provider is not None:
                try:
                    if hasattr(self.fallback_provider, "fetch_candles"):
                        candles = self.fallback_provider.fetch_candles(
                            symbol,
                            timeframe="m5",
                            max_count=self.incremental_limit,
                            since_ts=market_cache.get_last_timestamp(symbol),
                        )
                    else:
                        candles = self.fallback_provider.get_candles(
                            symbol,
                            timeframe="m5",
                            limit=self.incremental_limit,
                            since_ts=market_cache.get_last_timestamp(symbol),
                        )
                    if candles:
                        if isinstance(candles[0], Candle):
                            cache_candles = candles_to_cache_dicts(candles)
                            market_cache.upsert_candles(symbol, cache_candles)
                            logger.info(
                                f"Fallback ingested {len(cache_candles)} candles for {symbol}. Last: {cache_candles[-1]['time']}"
                            )
                        else:
                            market_cache.upsert_candles(symbol, candles)
                            logger.info(
                                f"Fallback ingested {len(candles)} candles for {symbol}. Last: {candles[-1]['time']}"
                            )
                except Exception as fe:
                    logger.warning(f"Fallback provider failed for {symbol}: {fe}")
            # Exponential backoff logic could go here
            await self._sleep_interruptible(1)

    def stop(self):
        self._running = False

# Helper to run in separate thread if needed, or straight async
def start_ingestor_thread(provider: MarketDataProvider):
    import threading
    def runner():
        asyncio.run(DataIngestor(provider).run_forever())
    
    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return t
