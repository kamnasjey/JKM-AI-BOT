from __future__ import annotations
import os, time, socket
from pathlib import Path
from fastapi import FastAPI, Query
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

def _ensure_writable_dir(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        t = p / ".write_test"
        t.write_text("ok", encoding="utf-8")
        t.unlink(missing_ok=True)
        return True
    except Exception:
        return False

@app.get("/health")
def health():
    massive_key = (os.getenv("MASSIVE_API_KEY") or "").strip()
    state_dir = Path(os.getenv("STATE_DIR") or "/app/state")
    writable = _ensure_writable_dir(state_dir)
    return {
        "ok": True,
        "ts": int(time.time()),
        "uptime_s": int(time.time() - APP_START),
        "hostname": socket.gethostname(),
        "provider_configured": bool(massive_key),
        "state_dir": str(state_dir),
        "state_writable": writable,
        "cache": {"ready": False, "note": "placeholder"},
        "db": {"ready": False, "note": "placeholder"},
    }

@app.get("/api/signals")
def list_signals(limit: int = Query(3, ge=1, le=100)):
    # Return empty list as requested for stability
    return []
