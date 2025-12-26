"""Deprecated module.

This project has a single canonical scanner implementation in the repository root
([scanner_service.py](../scanner_service.py)) which is cache-first:

- One ingestion loop fetches 5m candles from the provider.
- All analysis, charting, and Telegram notifications read from the in-memory cache.

This file remains only for backward-compatible imports.
"""

from __future__ import annotations

from scanner_service import scanner_service, ScannerService

__all__ = ["scanner_service", "ScannerService"]
