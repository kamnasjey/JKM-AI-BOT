from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class StrategyBuildResult:
    strategies: List[Dict[str, Any]]
    summary: str
    raw_model_text: str


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    m = _JSON_RE.search(text)
    if not m:
        return None
    candidate = m.group(0)
    try:
        return json.loads(candidate)
    except Exception:
        return None


def _normalize_tf(tf: Any, default: str) -> str:
    if not tf:
        return default
    s = str(tf).upper().replace(" ", "")
    # Accept common variants
    mapping = {
        "M5": "M15" if False else "M5",  # no-op placeholder for clarity
    }
    return mapping.get(s, s)


def _validate_strategy_obj(obj: Dict[str, Any]) -> Optional[str]:
    # Minimal validation; core engine will do data sufficiency checks.
    if not isinstance(obj.get("name"), str) or not obj["name"].strip():
        return "Strategy missing non-empty name"
    for k in ("trend_tf", "entry_tf"):
        if k in obj and obj[k] is not None and not isinstance(obj[k], str):
            return f"{k} must be string"
    if "min_rr" in obj and obj["min_rr"] is not None:
        try:
            float(obj["min_rr"])
        except Exception:
            return "min_rr must be number"
    if "min_risk" in obj and obj["min_risk"] is not None:
        try:
            float(obj["min_risk"])
        except Exception:
            return "min_risk must be number"
    blocks = obj.get("blocks")
    if blocks is not None and not isinstance(blocks, dict):
        return "blocks must be object"
    return None


def build_strategies_from_str_text(
    *,
    user_text: str,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_strategies: int = 1,
) -> StrategyBuildResult:
    """Use OpenAI to convert free-text STR strategy into structured strategy configs.

    Returns a list of strategy configs that match the engine profile schema.
    """

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError("openai package not installed") from e

    chosen_model = (model or os.getenv("OPENAI_MODEL_STRATEGY_BUILDER") or "gpt-4.1-mini").strip()

    schema_hint = {
        "strategies": [
            {
                "name": "string (short name)",
                "trend_tf": "H4|D1|H1|...",
                "entry_tf": "M15|M5|...",
                "min_rr": 3.0,
                "min_risk": 0.0,
                "blocks": {
                    "trend": {"ma_period": 50},
                    "fibo": {"levels": [0.5, 0.618]},
                },
            }
        ],
        "summary": "string (1-3 sentences, Mongolian)",
    }

    max_strategies = max(1, int(max_strategies or 1))

    system = (
        "You are a trading strategy compiler. "
        "Convert the user's Mongolian STR text into STRICT JSON matching the provided schema. "
        "Do not include markdown, code fences, or extra text. Output JSON only. "
        "Never invent real-time market facts. If information is missing, choose safe defaults."
    )

    user_msg = (
        "User STR text (Mongolian):\n"
        f"{user_text.strip()}\n\n"
        "Return JSON with keys: strategies (array) and summary (string).\n"
        f"Max strategies: {max_strategies}.\n"
        "Constraints / defaults:\n"
        "- If min_rr not specified, use 3.0.\n"
        "- If min_risk not specified, use 0.0.\n"
        "- If fibo levels not specified, use [0.5, 0.618].\n"
        "- If MA period not specified, use 50.\n"
        "- If timeframes not specified, use trend_tf=H4 and entry_tf=M15.\n\n"
        "Schema example (types only):\n"
        + json.dumps(schema_hint, ensure_ascii=False)
    )

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=chosen_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        temperature=float(temperature),
    )

    text = (resp.choices[0].message.content or "").strip()
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise ValueError("Model did not return valid JSON")

    strategies = data.get("strategies")
    summary = data.get("summary")

    if not isinstance(strategies, list) or not strategies:
        raise ValueError("JSON missing non-empty strategies array")
    if not isinstance(summary, str):
        summary = ""

    cleaned: List[Dict[str, Any]] = []
    for s in strategies[: max_strategies]:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "Strategy").strip() or "Strategy"
        trend_tf = _normalize_tf(s.get("trend_tf"), "H4")
        entry_tf = _normalize_tf(s.get("entry_tf"), "M15")
        min_rr = float(s.get("min_rr") if s.get("min_rr") is not None else 3.0)
        min_risk = float(s.get("min_risk") if s.get("min_risk") is not None else 0.0)
        blocks = s.get("blocks") if isinstance(s.get("blocks"), dict) else {}

        # Apply safe defaults
        blocks = dict(blocks)
        blocks.setdefault("trend", {})
        blocks.setdefault("fibo", {})
        if isinstance(blocks["trend"], dict):
            blocks["trend"].setdefault("ma_period", 50)
        if isinstance(blocks["fibo"], dict):
            blocks["fibo"].setdefault("levels", [0.5, 0.618])

        obj = {
            "name": name,
            "trend_tf": trend_tf,
            "entry_tf": entry_tf,
            "min_rr": min_rr,
            "min_risk": min_risk,
            "blocks": blocks,
        }
        err = _validate_strategy_obj(obj)
        if err:
            continue
        cleaned.append(obj)

    if not cleaned:
        raise ValueError("No valid strategies after validation")

    return StrategyBuildResult(strategies=cleaned, summary=summary.strip(), raw_model_text=text)
