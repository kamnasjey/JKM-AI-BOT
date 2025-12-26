# trading_service.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ig_client import IGClient
from config import WATCH_PAIRS
from user_profile import get_profile
from user_core_engine import scan_pair_with_profile_verbose
from analyzer import analyze_pair_multi_tf_ig_v2
from market_overview import get_market_overview_text
from ai_explainer import explain_signal_ganbayar

_IG_CLIENT: Optional[IGClient] = None


def _get_ig_client() -> IGClient:
    """IG client-оо нэг л удаа үүсгээд cache-лэнэ."""
    global _IG_CLIENT
    if _IG_CLIENT is None:
        _IG_CLIENT = IGClient.from_env()
    return _IG_CLIENT


def list_pairs() -> List[Dict[str, str]]:
    """config.WATCH_PAIRS-ийг frontend-д өгөх энгийн жагсаалт."""
    items: List[Dict[str, str]] = []
    for p in WATCH_PAIRS:
        items.append(
            {
                "symbol": p,
                "epic_env": f"EPIC_{p.replace('/', '')}",
            }
        )
    return items


def get_str_analysis(user_id: int, pair: str) -> Dict[str, Any]:
    """
    Хэрэглэгчийн профайл дээр тулгуурлаад pair-ийг шалгана.
    Setup байвал STR + AI тайлбар, байхгүй бол яагаад үгүйг reasons-ээр өгнө.
    """
    profile = get_profile(user_id)
    scan_res = scan_pair_with_profile_verbose(pair, profile)

    data: Dict[str, Any] = {
        "pair": pair,
        "profile": profile,
        "has_setup": scan_res.has_setup,
        "reasons": scan_res.reasons,
        "trend_tf": scan_res.trend_tf,
        "entry_tf": scan_res.entry_tf,
    }

    if scan_res.setup:
        setup = scan_res.setup
        setup_dict = {
            "direction": setup.direction,
            "entry": setup.entry,
            "sl": setup.sl,
            "tp": setup.tp,
            "rr": setup.rr,
        }
        data["setup"] = setup_dict

        # AI-д өгөх signal dict
        signal = {
            "pair": pair,
            "direction": setup.direction,
            "timeframe": scan_res.entry_tf,
            "entry": setup.entry,
            "sl": setup.sl,
            "tp": setup.tp,
            "rr": setup.rr,
            "context": {
                "h1_trend": getattr(scan_res.trend_info, "direction", None)
                if scan_res.trend_info
                else None,
            },
        }

        try:
            if os.getenv("OPENAI_API_KEY"):
                explanation = explain_signal_ganbayar(signal)
            else:
                explanation = "OPENAI_API_KEY тохируулаагүй тул AI STR тайлбар идэвхгүй байна."
        except Exception as e:
            explanation = f"AI STR тайлбар авахад алдаа гарлаа: {e}"

        data["ai_explanation"] = explanation
    else:
        data["setup"] = None
        data["ai_explanation"] = "Энэ pair дээр одоогоор STR setup илрээгүй."

    return data


def get_tech_analysis(pair: str) -> Dict[str, Any]:
    """
    analyzer.py ашиглаад multi-TF technical текст буцаана.
    """
    epic_env = f"EPIC_{pair.replace('/', '')}"
    epic = os.getenv(epic_env, "").strip()
    if not epic:
        return {
            "error": f"{epic_env} ENV тохируулагдаагүй байна (.env дээр EPIC_xxx нэм)."
        }

    ig = _get_ig_client()
    text = analyze_pair_multi_tf_ig_v2(ig, epic, pair)
    return {"analysis_text": text}


def get_macro_overview() -> Dict[str, str]:
    """
    market_overview.py ашиглаад ерөнхий macro/sentiment текст буцаана.
    """
    text = get_market_overview_text()
    return {"overview_text": text}
