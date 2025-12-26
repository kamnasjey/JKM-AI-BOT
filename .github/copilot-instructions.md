# JKM_TRADING_AI_BOT - Copilot Instructions

## Goal
Build an indicator-free (NO RSI/MACD/MA/ATR/BB/Ichimoku/VWAP/etc) technical analysis engine using plugin detectors, optimized for MarketDataCache + resample cache.

## Hard rules
- Do NOT add indicator-based methods. Price/structure/geometry/pattern/time only.
- Keep current architecture:
  - Engine logic in engine_blocks.py / user_core_engine.py / detectors modules
  - telegram_bot.py stays thin (only formatting + sending)
- Python 3, use existing libs only (httpx, apscheduler, matplotlib, requests, openai, dotenv).
- Use PEP8, type hints, dataclasses where appropriate.

## Engine design
- Feature precompute once per (symbol, tf, last_ts)
- Run enabled detectors from registry
- Return DetectorResult with evidence for Telegram explanation
- Apply scoring + RR filter + dedupe cooldown

## Output requirements
- Keep changes minimal and modular.
- Add tests under tests/ (pytest optional; otherwise tests/run_all.py)
