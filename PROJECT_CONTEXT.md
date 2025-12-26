# PROJECT_CONTEXT (JKM_TRADING_AI_BOT)

## Repo layout (high level)
- `market_data_cache.py`: Thread-safe in-memory cache for **M5 candles** (dicts with `time/open/high/low/close`). Also exposes `get_resampled(symbol, tf)` which memoizes `resample_5m.resample()` output.
- `resample_5m.py`: Pure resampling from M5 → higher TF candles.
- `core/primitives.py`: **Indicator-free primitives** (structure, fractal swings, clustered S/R zones, fib levels) computed once per `(symbol, tf, last_ts)`.
- `core/user_core_engine.py`: Pure scan pipelines (no HTTP/DB). Includes `scan_pair_cached_indicator_free(...)`.
- `engines/detectors/`: Indicator-free plugin detectors used by the indicator-free pipeline.
- `scanner_service.py`: Orchestration loop (reads cache → resamples → calls engine → emits `SignalEvent`).
- `services/notifier_telegram.py`: Telegram formatting/sending (thin).

## Indicator-free rule
- Do **NOT** implement or rely on indicators: RSI/MACD/MA/ATR/BB/Ichimoku/VWAP/Stochastic/ADX/etc.
- Allowed: price action, time/structure, geometry, swings/fractals, zones, patterns, fib retracements/extensions.
- Keep IO out of engine logic: detectors + engine functions should be deterministic and pure where possible.

## DetectorResult contract (indicator-free)
- Every detector returns a `DetectorResult` with (at minimum):
  - `match: bool`
  - `direction: Optional["BUY"|"SELL"]`
  - `confidence: float` (0..1)
  - `setup_name: str` (usually the detector name)
  - `evidence: List[str]` (may be empty)
- Optional setup fields may be included when the detector can provide them: entry/sl/tp/rr, zones, targets, invalidation, etc.

## Production hardening (next steps)
1) QA Gate tests (automated checks)
2) Structured logging + timing metrics
3) Signal cooldown + daily limit state persistence (survive restart)
4) Performance guard (detector runtime cap + cache hit/miss)
5) Telegram spam protection (conflict policy, min_score)
