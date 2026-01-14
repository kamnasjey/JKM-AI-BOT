from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import JSONResponse


app = FastAPI(title="JKM Web API", version="0.2.0")


def _require_account(_req: Request) -> Tuple[Dict[str, Any], str]:
    """Auth hook for dashboard API.

    Tests monkeypatch this. In production, wire it to your auth.
    """

    return ({"user_id": "anonymous", "is_admin": False}, "")


def get_signal_by_id_jsonl(**_kwargs: Any) -> Dict[str, Any]:
    """Signal lookup hook.

    Tests monkeypatch this. In production, implement lookup from jsonl/db.
    """

    return {}


@app.get("/api/candles")
def api_candles(
    symbol: str = Query(...),
    tf: str = Query("5m"),
    limit: int = Query(500, ge=1, le=5000),
):
    from market_data_cache import market_cache

    sym = str(symbol or "").upper().strip()
    candles = market_cache.get_candles(sym) or []
    if isinstance(candles, list) and limit > 0:
        candles = candles[-int(limit) :]

    return {"ok": True, "symbol": sym, "tf": str(tf), "candles": candles}


@app.get("/api/markets/{symbol}/candles")
def api_markets_candles(
    symbol: str,
    tf: str = Query("5m"),
    limit: int = Query(500, ge=1, le=5000),
):
    return api_candles(symbol=symbol, tf=tf, limit=limit)


@app.get("/api/detectors")
def api_detectors(include_docs: int = Query(0)):
    import detectors.registry as reg

    names = sorted([str(k) for k in (getattr(reg, "DETECTOR_REGISTRY", {}) or {}).keys()])
    if not include_docs:
        return {"detectors": names}

    dets = []
    for name in names:
        cls = (getattr(reg, "DETECTOR_REGISTRY", {}) or {}).get(name)
        doc = getattr(cls, "doc", None) if cls else None
        dets.append(
            {
                "name": name,
                "doc": str(doc) if isinstance(doc, str) else "",
                "params_schema": dict(getattr(cls, "params_schema", {}) or {}) if cls else {},
                "examples": list(getattr(cls, "examples", []) or []) if cls else [],
            }
        )

    return {"detectors": dets}


@app.get("/api/strategies")
def api_get_strategies(req: Request):
    acct, _token = _require_account(req)
    user_id = str((acct or {}).get("user_id") or "unknown")

    from core.user_strategies_store import load_user_strategies

    return {"user_id": user_id, "strategies": load_user_strategies(user_id)}


@app.put("/api/strategies")
def api_put_strategies(req: Request, payload: Dict[str, Any] = Body(...)):
    acct, _token = _require_account(req)
    user_id = str((acct or {}).get("user_id") or "unknown")

    from core.user_strategies_store import save_user_strategies, validate_normalize_user_strategies

    raw_items = (payload or {}).get("strategies")
    normalized, errors = validate_normalize_user_strategies(raw_items)
    if errors and not normalized:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "invalid_strategies",
                "user_id": user_id,
                "strategies": [],
                "warnings": list(errors),
            },
        )

    res = save_user_strategies(user_id, raw_items)
    if not bool(res.get("ok")):
        return JSONResponse(status_code=400, content=res)
    return res


@app.get("/api/signals/{signal_id}")
def api_signal_detail(req: Request, signal_id: str):
    _acct, _token = _require_account(req)

    from core.signal_payload_public_v1 import to_public_v1_from_legacy_dict

    legacy = get_signal_by_id_jsonl(signal_id=str(signal_id))
    pub = to_public_v1_from_legacy_dict(legacy if isinstance(legacy, dict) else {})
    return pub.model_dump(mode="json")


@app.get("/api/signal/{signal_id}")
def api_signal_alias(req: Request, signal_id: str):
    return api_signal_detail(req=req, signal_id=signal_id)
