from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


_TF_LIST = ("M5", "M15", "H1", "H4", "D1")


def coverage_for_symbol(cache: Any, symbol: str) -> Dict[str, int]:
    """Return bar counts available for a canonical symbol across key TFs.

    Expected cache interface:
    - get_candles(symbol) -> list
    - get_resampled(symbol, tf) -> list
    """

    sym = str(symbol or "").strip().upper()
    out: Dict[str, int] = {tf: 0 for tf in _TF_LIST}

    try:
        out["M5"] = len(cache.get_candles(sym) or [])
    except Exception:
        out["M5"] = 0

    for tf in ("M15", "H1", "H4", "D1"):
        try:
            out[tf] = len(cache.get_resampled(sym, tf) or [])
        except Exception:
            out[tf] = 0

    return out


def readiness_check(
    cache: Any,
    symbol: str,
    trend_tf: str,
    entry_tf: str,
    min_trend_bars: Optional[int],
    min_entry_bars: Optional[int],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Determine if cache coverage is sufficient to run detectors.

    Returns:
      (ready, reason, details)

    reason:
      - "ok"
      - "data_gap"

    details includes have/need for trend/entry TF.
    """

    sym = str(symbol or "").strip().upper()
    trend = str(trend_tf or "").strip().upper()
    entry = str(entry_tf or "").strip().upper()

    cov = coverage_for_symbol(cache, sym)

    have_trend = int(cov.get(trend, 0))
    have_entry = int(cov.get(entry, 0))

    # If inputs are missing/unparseable, fall back to sane defaults.
    # (Avoid any sentinel values; production should always use real thresholds.)
    try:
        need_trend = int(min_trend_bars) if min_trend_bars is not None else 55
    except Exception:
        need_trend = 55
    try:
        need_entry = int(min_entry_bars) if min_entry_bars is not None else 200
    except Exception:
        need_entry = 200

    ok = (have_trend >= need_trend) and (have_entry >= need_entry)
    if ok:
        return True, "ok", {"coverage": cov}

    details: Dict[str, Any] = {
        "coverage": cov,
        "trend_tf": trend,
        "entry_tf": entry,
        "have_trend": have_trend,
        "need_trend": need_trend,
        "have_entry": have_entry,
        "need_entry": need_entry,
    }
    return False, "data_gap", details
