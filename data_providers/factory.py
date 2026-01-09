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
    return os.getenv("MARKET_DATA_PROVIDER", "massive").strip().lower()


def create_provider(*, name: Optional[str] = None) -> DataProvider:
    provider = (name or _env_provider_name()).strip().lower()

    if provider in ("massive", "massiveio", "massive_io"):
        from .massive_provider import MassiveDataProvider

        return MassiveDataProvider()

    if provider in ("ig", "igmarkets", "ig_markets"):
        raise ValueError(
            "IG provider support has been removed. Set DATA_PROVIDER=massive (recommended) or DATA_PROVIDER=simulation."
        )

    # Default safe provider (no external IO)
    from .simulation_provider import SimulationDataProvider

    return SimulationDataProvider()
