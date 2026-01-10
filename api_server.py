from __future__ import annotations
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Query
from fastapi import Body
from fastapi.middleware.cors import CORSMiddleware

APP_START = time.time()
app = FastAPI(title="JKM-AI-BOT API", version="0.1.0")

def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if raw == "":
        return default
    return raw in {"1", "true", "yes", "y", "on"}


cors_allow_all = _env_bool("CORS_ALLOW_ALL", default=False)
if cors_allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"]
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://jkmcopilot.com",
            "https://www.jkmcopilot.com",
        ],
        allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"]
    )

# ---- STARTUP: launch background scanner scheduler ----
@app.on_event("startup")
def _startup_scanner():
    """Launch the APScheduler-based 5-minute scan cycle on server start."""
    import logging
    _log = logging.getLogger("api_server.startup")
    try:
        import scanner_service
        result = scanner_service.start()
        _log.info("Scanner scheduler started: %s", result)
    except Exception as e:
        _log.error("Failed to start scanner scheduler: %s", e, exc_info=True)

def _ensure_writable_dir(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        t = p / ".write_test"
        t.write_text("ok", encoding="utf-8")
        t.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _signals_path() -> Path:
    state_dir = Path(os.getenv("STATE_DIR") or "/app/state")
    return state_dir / "signals.jsonl"


def _estimate_lines_fast(file_path: Path) -> int:
    try:
        st = file_path.stat()
    except Exception:
        return 0

    size = int(getattr(st, "st_size", 0) or 0)
    if size <= 0:
        return 0

    sample_size = min(64 * 1024, size)
    try:
        with file_path.open("rb") as f:
            f.seek(-sample_size, os.SEEK_END)
            tail = f.read(sample_size)
    except Exception:
        return 0

    newlines = tail.count(b"\n")
    if newlines <= 0:
        return 1

    avg_bytes_per_line = max(1, sample_size // newlines)
    return max(1, size // avg_bytes_per_line)


def _read_last_json_objects(file_path: Path, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    if not file_path.exists():
        return []

    # Read from the end in chunks until we have enough lines.
    # We parse from the end so we can return the last N valid JSON objects.
    chunk_size = 8192
    max_bytes = 4 * 1024 * 1024  # safety cap
    data = b""
    read_total = 0

    try:
        with file_path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            while pos > 0 and read_total < max_bytes and data.count(b"\n") < (limit * 3 + 10):
                step = min(chunk_size, pos)
                pos -= step
                f.seek(pos)
                block = f.read(step)
                read_total += len(block)
                data = block + data
    except Exception:
        return []

    text = data.decode("utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    out: list[dict[str, Any]] = []
    for ln in reversed(lines):
        if len(out) >= limit:
            break
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)

    out.reverse()
    return out

@app.get("/health")
def health():
    massive_key = (os.getenv("MASSIVE_API_KEY") or "").strip()
    # MASSIVE_BASE_URL is optional; provider defaults to https://api.massive.com.
    massive_base_url = (os.getenv("MASSIVE_BASE_URL") or "").strip() or "https://api.massive.com"
    data_provider = (os.getenv("DATA_PROVIDER") or os.getenv("MARKET_DATA_PROVIDER") or "").strip().lower()
    state_dir = Path(os.getenv("STATE_DIR") or "/app/state")
    writable = _ensure_writable_dir(state_dir)

    signals_file = state_dir / "signals.jsonl"
    signals_exists = signals_file.exists()
    signals_lines_estimate = _estimate_lines_fast(signals_file) if signals_exists else 0

    # Cache readiness: best-effort snapshot of in-memory market cache.
    cache_ready = False
    cache_note = "not_loaded"
    cache_symbols = 0
    try:
        from market_data_cache import market_cache  # local module, no external deps

        syms = market_cache.get_all_symbols()
        cache_symbols = int(len(syms))
        cache_ready = cache_symbols > 0
        cache_note = "ok" if cache_ready else "empty"
    except Exception:
        cache_ready = False
        cache_note = "unavailable"
        cache_symbols = 0

    # DB readiness: v0.1 backend does not require a DB.
    db_ready = True
    db_note = "not_configured"
    return {
        "ok": True,
        "ts": int(time.time()),
        "uptime_s": int(time.time() - APP_START),
        "hostname": socket.gethostname(),
        "provider_configured": bool(massive_key and massive_base_url),
        "provider_env": data_provider or None,
        "massive_api_key_present": bool(massive_key),
        "massive_base_url_present": bool(massive_base_url),
        "state_dir": str(state_dir),
        "state_writable": writable,
        "signals_file_exists": bool(signals_exists),
        "signals_lines_estimate": int(signals_lines_estimate),
        "cache": {"ready": bool(cache_ready), "note": str(cache_note), "symbols": int(cache_symbols)},
        "db": {"ready": bool(db_ready), "note": str(db_note)},
    }

@app.get("/api/signals")
def list_signals(limit: int = Query(50, ge=1, le=500)):
    path = _signals_path()
    return _read_last_json_objects(path, limit)


@app.post("/api/signals")
def append_signal(payload: dict[str, Any] = Body(...)):
    state_dir = Path(os.getenv("STATE_DIR") or "/app/state")
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # If we cannot create state dir, fail gracefully (no crash).
        return {"ok": False, "error": "state_dir_not_writable"}

    if "ts" not in payload:
        payload["ts"] = int(time.time())

    file_path = state_dir / "signals.jsonl"
    try:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with file_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        return {"ok": False, "error": "write_failed"}

    return {"ok": True}
# =========================
# Engine control v0.1 (internal-key protected)
# =========================
import os
import time
import threading
from typing import Any, Callable, Optional

from fastapi import Header, HTTPException, Depends

def require_internal_key(
    x_internal_api_key: Optional[str] = Header(default=None, alias="x-internal-api-key")
) -> bool:
    expected = os.getenv("INTERNAL_API_KEY")
    if not expected:
        # safer: misconfigured server
        raise HTTPException(status_code=500, detail="INTERNAL_API_KEY not configured")
    if not x_internal_api_key or x_internal_api_key != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
    return True

class EngineController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started_at = time.time()
        self.running: bool = False
        self.last_scan_ts: Optional[int] = None
        self.last_error: Optional[str] = None

    def _resolve_scan_once(self) -> Callable[[], Any]:
        """
        Tries to find a 'scan once' function from scanner_service.py without hard-coding.
        You can later replace this with the exact function call.
        """
        import scanner_service as ss  # local import to avoid import-time crashes
        for name in ("scan_once", "run_once", "manual_scan", "do_scan_once", "scan_cycle"):
            fn = getattr(ss, name, None)
            if callable(fn):
                return fn
        raise RuntimeError("No scan-once function found in scanner_service.py")

    def _loop(self, cadence_s: int = 300) -> None:
        while not self._stop_event.is_set():
            try:
                self.manual_scan()
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
            # sleep in small chunks so stop feels responsive
            for _ in range(max(1, cadence_s)):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def start(self) -> dict:
        with self._lock:
            if self.running and self._thread and self._thread.is_alive():
                return self.status()

            self._stop_event.clear()
            self.last_error = None

            self._thread = threading.Thread(target=self._loop, name="engine-loop", daemon=True)
            self._thread.start()
            self.running = True
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
            self.running = False
            return self.status()

    def manual_scan(self) -> dict:
        try:
            scan_once = self._resolve_scan_once()
            result = scan_once()
            self.last_scan_ts = int(time.time())
            self.last_error = None
            return {"ok": True, "result": result, "ts": self.last_scan_ts}
        except Exception as e:
            self.last_scan_ts = int(time.time())
            self.last_error = f"{type(e).__name__}: {e}"
            return {"ok": False, "error": self.last_error, "ts": self.last_scan_ts}

    def status(self) -> dict:
        uptime_s = int(time.time() - self._started_at)
        alive = bool(self._thread and self._thread.is_alive())
        return {
            "ok": True,
            "running": bool(self.running and alive),
            "uptime_s": uptime_s,
            "last_scan_ts": self.last_scan_ts,
            "last_error": self.last_error,
        }

_engine = EngineController()

@app.get("/api/engine/status", dependencies=[Depends(require_internal_key)])
def engine_status():
    return _engine.status()

@app.post("/api/engine/start", dependencies=[Depends(require_internal_key)])
def engine_start():
    return _engine.start()

@app.post("/api/engine/stop", dependencies=[Depends(require_internal_key)])
def engine_stop():
    return _engine.stop()

@app.post("/api/engine/manual-scan", dependencies=[Depends(require_internal_key)])
def engine_manual_scan():
    return _engine.manual_scan()


@app.post("/api/scan/manual-explain", dependencies=[Depends(require_internal_key)])
def scan_manual_explain(payload: dict):
    """Run a one-off manual scan for a specific user and return a Telegram-ready explanation.

    Payload:
      - user_id: str (required)
      - symbols: list[str] (optional)
    """

    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    symbols = payload.get("symbols")
    if symbols is not None and not isinstance(symbols, list):
        raise HTTPException(status_code=400, detail="symbols must be a list")

    import scanner_service as ss

    return ss.scanner_service.manual_scan_explain(user_id=user_id, symbols=symbols)

# Dashboard login flow sometimes calls this; stop returning 404.
# Keep it internal-key protected (recommended).
@app.post("/api/auth/register", dependencies=[Depends(require_internal_key)])
def auth_register(payload: dict):
    # v0.1 minimal: just acknowledge; later you can store into sqlite user_db.py
    return {"ok": True, "registered": True, "payload_keys": list(payload.keys())}


# =========================
# Admin backfill (internal-key protected)
# =========================


@app.post("/api/admin/backfill", dependencies=[Depends(require_internal_key)])
def admin_backfill(payload: dict):
    """Run a short backfill job into /app/state/marketdata.

    Intended for ops validation (small ranges). Heavy multi-year backfills should
    use scripts/backfill_massive.py.

    Payload:
      - symbol: str (required)
      - timeframe: str (default: m5)
      - days: int (default: 7)
      - chunk_days: int (default: 1)
    """

    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol required")

    timeframe = str(payload.get("timeframe") or "m5").strip().lower() or "m5"
    days = int(payload.get("days") or 7)
    chunk_days = int(payload.get("chunk_days") or 1)
    days = max(1, min(days, 30))
    chunk_days = max(1, min(chunk_days, 14))

    # Run in background so API stays responsive.
    def _job() -> None:
        import time
        import logging
        from datetime import datetime, timedelta, timezone

        from core.ingest_debug import log_ingest_event
        from core.marketdata_store import append as store_append
        from data_providers.factory import create_provider
        from data_providers.models import Candle, candles_to_cache_dicts
        from data_providers.massive_provider import to_massive_ticker

        provider = create_provider(name="massive")

        job_logger = logging.getLogger("uvicorn.error")

        job_logger.info(
            "ADMIN_BACKFILL_START symbol=%s tf=%s days=%s chunk_days=%s",
            symbol,
            timeframe,
            days,
            chunk_days,
        )

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)

        cur = start
        step = timedelta(days=chunk_days)
        while cur < end:
            nxt = min(end, cur + step)
            est = int((nxt - cur).total_seconds() / 300) + 20
            t0 = time.perf_counter()
            candles = provider.fetch_candles(
                symbol,
                timeframe=timeframe,
                max_count=est,
                limit=est,
                since_ts=cur,
                until_ts=nxt,
            )
            dt_ms = (time.perf_counter() - t0) * 1000.0
            cache_dicts = candles_to_cache_dicts(candles) if candles else []
            _, persisted_path = store_append(symbol, timeframe, cache_dicts)

            job_logger.info(
                "ADMIN_BACKFILL_CHUNK symbol=%s tf=%s start=%s end=%s fetched=%d wrote=%d ms=%.2f",
                symbol,
                timeframe,
                cur.isoformat(),
                nxt.isoformat(),
                int(len(candles or [])),
                int(len(cache_dicts)),
                float(dt_ms),
            )

            massive_ticker = None
            try:
                massive_ticker = to_massive_ticker(symbol)
            except Exception:
                massive_ticker = None

            log_ingest_event(
                job_logger,
                "admin_backfill_chunk",
                provider=getattr(provider, "name", "unknown"),
                symbol=symbol,
                timeframe=timeframe,
                candles_count=int(len(cache_dicts)),
                requested_start=cur.isoformat(),
                requested_end=nxt.isoformat(),
                persist_path=str(persisted_path),
                duration_ms=dt_ms,
                extra={
                    "internalSymbol": symbol,
                    "massiveTicker": massive_ticker,
                    "fetchedCandles": int(len(candles or [])),
                },
            )
            # small pacing to be gentle
            time.sleep(0.1)
            cur = nxt

    t = threading.Thread(target=_job, name=f"admin-backfill-{symbol}", daemon=True)
    t.start()
    return {"ok": True, "started": True, "symbol": symbol, "timeframe": timeframe, "days": days, "chunk_days": chunk_days}


# ============================================================================
# USER STRATEGY & DETECTOR API ENDPOINTS
# ============================================================================

@app.get("/api/detectors")
async def list_detectors():
    """List all available detectors with metadata."""
    from detectors.registry import DETECTOR_REGISTRY, get_detector
    
    result = []
    for name in sorted(DETECTOR_REGISTRY.keys()):
        try:
            det = get_detector(name)
            if det:
                result.append({
                    "name": name,
                    "doc": det.get_doc() if hasattr(det, "get_doc") else "",
                    "params_schema": det.get_params_schema() if hasattr(det, "get_params_schema") else {},
                    "examples": det.get_examples() if hasattr(det, "get_examples") else [],
                })
        except Exception:
            result.append({"name": name, "doc": "", "params_schema": {}, "examples": []})
    
    return {"ok": True, "detectors": result, "count": len(result)}


@app.get("/api/presets")
async def list_presets():
    """List available strategy presets."""
    import glob
    presets = []
    for f in glob.glob("config/presets/*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.loads(fp.read())
                presets.append({
                    "preset_id": data.get("preset_id", Path(f).stem),
                    "strategies": data.get("strategies", []),
                })
        except Exception:
            pass
    return {"ok": True, "presets": presets, "count": len(presets)}


@app.get("/api/user/{user_id}/strategies")
async def get_user_strategies(user_id: str, api_key: str = Depends(require_internal_key)):
    """Get user's saved strategies."""
    from core.user_strategies_store import load_user_strategies
    
    strategies = load_user_strategies(user_id)
    return {"ok": True, "user_id": user_id, "strategies": strategies, "count": len(strategies)}


@app.post("/api/user/{user_id}/strategies")
async def save_user_strategies_endpoint(
    user_id: str,
    payload: dict = Body(...),
    api_key: str = Depends(require_internal_key)
):
    """Save user's strategies.
    
    Body: {"strategies": [...]}
    Each strategy should have:
      - strategy_id: unique name
      - enabled: true/false
      - detectors: ["detector1", "detector2", ...]
      - min_score: float (default 1.0)
      - min_rr: float (default 2.0)
      - allowed_regimes: ["RANGE", "TREND_BULL", "TREND_BEAR", "CHOP"]
    """
    from core.user_strategies_store import save_user_strategies
    
    strategies = payload.get("strategies", [])
    result = save_user_strategies(user_id, strategies)
    return result


@app.delete("/api/user/{user_id}/strategies")
async def delete_user_strategies(user_id: str, api_key: str = Depends(require_internal_key)):
    """Delete all user strategies."""
    from core.user_strategies_store import user_strategies_path
    
    path = user_strategies_path(user_id)
    try:
        path.unlink(missing_ok=True)
        return {"ok": True, "user_id": user_id, "deleted": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/user/{user_id}/strategies/from-preset/{preset_id}")
async def copy_preset_to_user(
    user_id: str,
    preset_id: str,
    api_key: str = Depends(require_internal_key)
):
    """Copy a preset to user's strategies."""
    from core.user_strategies_store import save_user_strategies
    
    preset_path = Path(f"config/presets/{preset_id}.json")
    if not preset_path.exists():
        raise HTTPException(status_code=404, detail=f"Preset '{preset_id}' not found")
    
    try:
        with open(preset_path, "r", encoding="utf-8") as fp:
            data = json.loads(fp.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load preset: {e}")
    
    strategies = data.get("strategies", [])
    result = save_user_strategies(user_id, strategies)
    return result


# =========================
# Telegram Connect Flow (v0.2)
# =========================
@app.post("/api/telegram/connect-url", dependencies=[Depends(require_internal_key)])
def telegram_connect_url(payload: dict):
    """Generate a Telegram deep link for user to connect their chat.
    
    Payload:
      - user_id: str (required)
    
    Returns:
      - ok: bool
      - url: str (deep link to open bot with start token)
    """
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    
    from core.event_queue import create_connect_token, init_db
    
    # Ensure DB exists
    try:
        init_db()
    except Exception:
        pass
    
    token = create_connect_token(user_id, expires_in_s=1800)  # 30 min
    if not token:
        raise HTTPException(status_code=500, detail="Failed to create connect token")
    
    bot_username = os.getenv("TELEGRAM_BOT_USERNAME", "JKMCopilotBot")
    deep_link = f"https://t.me/{bot_username}?start={token}"
    
    return {"ok": True, "url": deep_link, "expires_in_s": 1800}


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, secret: str = ""):
    """Telegram webhook endpoint for /start connect flow.
    
    Query param:
      - secret: must match TELEGRAM_WEBHOOK_SECRET
    """
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not expected_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
    if secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    
    try:
        body = await request.json()
    except Exception:
        return {"ok": True}  # Telegram expects 200 even on parse failure
    
    # Handle /start <token> message
    message = body.get("message", {})
    text = str(message.get("text") or "").strip()
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    
    if not chat_id:
        return {"ok": True}
    
    # Check for /start command with token
    if text.startswith("/start "):
        token = text[7:].strip()
        if token:
            from core.event_queue import validate_connect_token, init_db
            from user_db import set_telegram_chat
            
            try:
                init_db()
            except Exception:
                pass
            
            user_id = validate_connect_token(token)
            if user_id:
                # Bind chat_id to user
                set_telegram_chat(user_id, str(chat_id))
                
                # Send confirmation message
                try:
                    from services.notifier_telegram import telegram_notifier
                    telegram_notifier.send_message(
                        "✅ Telegram connected!\n\nТа одоо setup илэрсэн үед Telegram-аар мэдэгдэл хүлээн авах болно.",
                        chat_id=chat_id,
                    )
                except Exception:
                    pass
                
                return {"ok": True, "connected": True}
            else:
                # Invalid/expired token
                try:
                    from services.notifier_telegram import telegram_notifier
                    telegram_notifier.send_message(
                        "❌ Token expired or invalid.\n\nШинэ холболтын линк авна уу.",
                        chat_id=chat_id,
                    )
                except Exception:
                    pass
    
    return {"ok": True}


@app.get("/api/telegram/status/{user_id}", dependencies=[Depends(require_internal_key)])
def telegram_status(user_id: str):
    """Check Telegram connection status for a user."""
    from user_db import get_telegram_chat, get_telegram_enabled
    
    chat_id = get_telegram_chat(user_id)
    enabled = get_telegram_enabled(user_id)
    
    connected = bool(chat_id)
    # Mask chat_id for security (show only last 4 digits)
    masked_chat = f"***{str(chat_id)[-4:]}" if chat_id else None
    
    return {
        "ok": True,
        "user_id": user_id,
        "connected": connected,
        "enabled": enabled,
        "chat_id_masked": masked_chat,
    }


@app.post("/api/telegram/toggle/{user_id}", dependencies=[Depends(require_internal_key)])
def telegram_toggle(user_id: str, payload: dict):
    """Enable/disable Telegram notifications for a user.
    
    Payload:
      - enabled: bool
    """
    from user_db import set_telegram_enabled
    
    enabled = bool(payload.get("enabled", True))
    success = set_telegram_enabled(user_id, enabled)
    
    return {"ok": success, "user_id": user_id, "enabled": enabled}

