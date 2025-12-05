# user_core_engine.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ig_client import IGClient
from engine_blocks import (
    normalize_candles,
    detect_trend,
    find_last_swing,
    check_fibo_retrace_zone,
    build_basic_setup,
    Setup,
    TrendInfo,
    FiboZoneInfo,
)

_IG_CLIENT: Optional[IGClient] = None


def _get_ig_client() -> IGClient:
    global _IG_CLIENT
    if _IG_CLIENT is not None:
        return _IG_CLIENT

    is_demo_env = os.getenv("IG_IS_DEMO", "false").lower()
    is_demo = is_demo_env in ("1", "true", "yes")

    _IG_CLIENT = IGClient.from_env(is_demo=is_demo)
    return _IG_CLIENT


def _get_epic_for_pair(pair: str) -> Optional[str]:
    key = f"EPIC_{pair.replace('/', '')}"
    epic = os.getenv(key, "").strip()
    return epic or None


# --- timeframe -> IG resolution map ---

def tf_to_ig_resolution(tf: str) -> str:
    """
    STR профайлаас ирсэн timeframe-ийг IG resolution руу хөрвүүлнэ.
    Дэмжиж байгаа TF-ууд: M1, M5, M15, M30, H1, H4, D1
    """
    tf = (tf or "").upper().replace(" ", "")

    mapping = {
        "M1": "MINUTE",
        "M5": "MINUTE_5",
        "M15": "MINUTE_15",
        "M30": "MINUTE_30",
        "H1": "HOUR",
        "H4": "HOUR_4",
        "D1": "DAY",
    }
    return mapping.get(tf, "MINUTE_15")


# ----------- ScanResult: setup байгаагүй үед ч тайлбартай -----------

@dataclass
class ScanResult:
    pair: str
    has_setup: bool
    setup: Optional[Setup]
    reasons: List[str]
    trend_info: Optional[TrendInfo] = None
    fibo_info: Optional[FiboZoneInfo] = None
    trend_tf: str = "H4"
    entry_tf: str = "M15"


# ----------- Дотоод core функц -----------

def _scan_pair_core(
    pair: str,
    profile: Dict[str, Any],
    max_points_trend: int = 200,
    max_points_entry: int = 300,
) -> ScanResult:
    """
    Нэг pair-ийг хэрэглэгчийн профайл дээр үндэслэн шалгана.
    Setup гарсан/гараагүй эсэх + “яагаад” гэдгийг reasons-ээр буцаана.
    """
    reasons: List[str] = []

    epic = _get_epic_for_pair(pair)
    if not epic:
        reasons.append("EPIC тохируулагдаагүй тул IG-аас өгөгдөл авч чадсангүй.")
        return ScanResult(pair, False, None, reasons)

    ig = _get_ig_client()

    # --- профайл параметрүүд ---
    min_rr = float(profile.get("min_rr", 3.0))
    risk_pips = float(profile.get("risk_pips", 10.0))

    trend_tf = str(profile.get("trend_tf", "H4")).upper()
    entry_tf = str(profile.get("entry_tf", "M15")).upper()

    trend_res = tf_to_ig_resolution(trend_tf)
    entry_res = tf_to_ig_resolution(entry_tf)

    blocks_cfg: Dict[str, Any] = profile.get("blocks", {})
    trend_cfg = blocks_cfg.get("trend", {}) or {}
    fibo_cfg = blocks_cfg.get("fibo", {}) or {}

    ma_period = int(trend_cfg.get("ma_period", 50))
    fibo_levels = tuple(fibo_cfg.get("levels", [0.5, 0.618]))

    try:
        # 1) Candles авах
        raw_trend = ig.get_candles(
            epic, resolution=trend_res, max_points=max_points_trend
        )
        raw_entry = ig.get_candles(
            epic, resolution=entry_res, max_points=max_points_entry
        )

        if not raw_trend or not raw_entry:
            reasons.append(
                f"IG-аас {trend_tf}/{entry_tf} timeframe дээр хангалттай лааны мэдээлэл ирсэнгүй."
            )
            return ScanResult(
                pair,
                False,
                None,
                reasons,
                trend_info=None,
                fibo_info=None,
                trend_tf=trend_tf,
                entry_tf=entry_tf,
            )

        trend_candles = normalize_candles(raw_trend, utc_offset_hours=8)
        entry_candles = normalize_candles(raw_entry, utc_offset_hours=8)

        # 2) Trend
        trend_info = detect_trend(trend_candles, ma_period=ma_period)
        if trend_info.direction == "flat":
            reasons.append(
                f"{trend_tf} дээр MA({ma_period})-аар тодорхой up/down тренд алга "
                f"(direction = {trend_info.direction})."
            )
            return ScanResult(
                pair,
                False,
                None,
                reasons,
                trend_info=trend_info,
                fibo_info=None,
                trend_tf=trend_tf,
                entry_tf=entry_tf,
            )

        # 3) Swing (entry TF дээр)
        swing = find_last_swing(
            entry_candles,
            lookback=int(fibo_cfg.get("lookback", 80)),
            direction=trend_info.direction,
        )
        if swing is None:
            reasons.append(
                f"{entry_tf} дээр хангалттай swing үүсээгүй, эсвэл low/high буруу байна."
            )
            return ScanResult(
                pair,
                False,
                None,
                reasons,
                trend_info=trend_info,
                fibo_info=None,
                trend_tf=trend_tf,
                entry_tf=entry_tf,
            )

        # 4) Fibo retrace zone
        fibo_info = check_fibo_retrace_zone(
            entry_candles,
            swing=swing,
            levels=fibo_levels,
        )

        if not fibo_info.in_zone:
            reasons.append(
                f"{entry_tf} дээрх сүүлийн хаалтын үнэ Fibo retrace бүсэд ороогүй байна.\n"
                f"Fibo бүс: {fibo_info.zone_low:.5f} – {fibo_info.zone_high:.5f}, "
                f"одоо хаалт: {fibo_info.last_close:.5f}."
            )
            return ScanResult(
                pair,
                False,
                None,
                reasons,
                trend_info=trend_info,
                fibo_info=fibo_info,
                trend_tf=trend_tf,
                entry_tf=entry_tf,
            )

        # 5) Setup (RR)
        setup = build_basic_setup(
            pair=pair,
            trend=trend_info,
            fibo=fibo_info,
            risk_pips=risk_pips,
            min_rr=min_rr,
        )
        if setup is None:
            reasons.append(
                "Entry/SL/TP тооцоололд профайлын нөхцөл хангагдсангүй "
                f"(RR < {min_rr} эсвэл SL/TP алдаатай)."
            )
            return ScanResult(
                pair,
                False,
                None,
                reasons,
                trend_info=trend_info,
                fibo_info=fibo_info,
                trend_tf=trend_tf,
                entry_tf=entry_tf,
            )

        # БҮХ нөхцөл хангагдсан
        reasons.append(
            f"Trend {trend_info.direction.upper()} ({trend_tf}), "
            f"үнэ {entry_tf} дээр Fibo бүсэд байна, RR ≈ {setup.rr:.2f} ≥ {min_rr}."
        )
        return ScanResult(
            pair,
            True,
            setup,
            reasons,
            trend_info=trend_info,
            fibo_info=fibo_info,
            trend_tf=trend_tf,
            entry_tf=entry_tf,
        )

    except Exception as e:
        reasons.append(f"Engine алдаа: {e}")
        return ScanResult(
            pair,
            False,
            None,
            reasons,
            trend_info=None,
            fibo_info=None,
            trend_tf=trend_tf,
            entry_tf=entry_tf,
        )


# ----------- Гаднаас дуудах интерфэйс -----------

def scan_pair_with_profile(
    pair: str,
    profile: Dict[str, Any],
    max_points_trend: int = 200,
    max_points_entry: int = 300,
) -> Optional[Setup]:
    """
    Хуучин интерфейс – зөвхөн setup хэрэгтэй үед (autoscan гэх мэт).
    """
    res = _scan_pair_core(pair, profile, max_points_trend, max_points_entry)
    return res.setup if res.has_setup else None


def scan_pair_with_profile_verbose(
    pair: str,
    profile: Dict[str, Any],
    max_points_trend: int = 200,
    max_points_entry: int = 300,
) -> ScanResult:
    """
    Гарын авлагаар шалгах үед – үргэлж ScanResult буцаана (тайлбартай).
    """
    return _scan_pair_core(pair, profile, max_points_trend, max_points_entry)


def scan_many_pairs_with_profile(
    pairs: List[str],
    profile: Dict[str, Any],
) -> List[Setup]:
    """
    Олон pair-ийг хуучин маягаар – зөвхөн setup-тайг нь буцаана.
    """
    results: List[Setup] = []
    for p in pairs:
        s = scan_pair_with_profile(p, profile=profile)
        if s is not None:
            results.append(s)
    return results


def scan_many_pairs_with_profile_verbose(
    pairs: List[str],
    profile: Dict[str, Any],
) -> List[ScanResult]:
    """
    Олон pair-ийг тайлбартай ScanResult хэлбэрээр буцаана.
    """
    res: List[ScanResult] = []
    for p in pairs:
        res.append(scan_pair_with_profile_verbose(p, profile=profile))
    return res
