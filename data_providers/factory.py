from __future__ import annotations

import os
from typing import Optional

from .base import DataProvider


def _env_provider_name() -> str:
    # New: DATA_PROVIDER
    raw = os.getenv("DATA_PROVIDER")
    if raw and raw.strip():
        return raw.strip().lower()
    # Back-compat: MARKET_DATA_PROVIDER
    return os.getenv("MARKET_DATA_PROVIDER", "simulation").strip().lower()


def create_provider(*, name: Optional[str] = None) -> DataProvider:
    provider = (name or _env_provider_name()).strip().lower()

    if provider in ("ig", "igmarkets", "ig_markets"):
        from ig_client import IGClient
        from .ig_provider import IGDataProvider

        client = IGClient.from_env()
        return IGDataProvider(client)

    # Default safe provider (no external IO)
    from .simulation_provider import SimulationDataProvider

    return SimulationDataProvider()
