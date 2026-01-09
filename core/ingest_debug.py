from __future__ import annotations

import os
import time
import logging
from typing import Any, Mapping, Optional


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def ingest_debug_enabled() -> bool:
    return _env_bool("DEBUG_INGEST", default=False)


def log_ingest_event(
    logger: logging.Logger,
    event: str,
    *,
    provider: str,
    symbol: str,
    timeframe: str,
    candles_count: int,
    requested_start: Optional[str] = None,
    requested_end: Optional[str] = None,
    persist_path: Optional[str] = None,
    duration_ms: Optional[float] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    if not ingest_debug_enabled():
        return

    payload: dict[str, Any] = {
        "event": str(event),
        "provider": str(provider),
        "symbol": str(symbol).upper(),
        "tf": str(timeframe),
        "candles": int(candles_count),
        "ts": int(time.time()),
    }
    if requested_start:
        payload["start"] = requested_start
    if requested_end:
        payload["end"] = requested_end
    if persist_path:
        payload["persist"] = persist_path
    if duration_ms is not None:
        payload["ms"] = round(float(duration_ms), 2)
    if extra:
        # Keep extra shallow and non-secret.
        for k, v in extra.items():
            if v is None:
                continue
            payload[str(k)] = v

    try:
        logger.info("INGEST_DEBUG %s", payload)
    except Exception:
        # Never break ingestion due to logging.
        pass
