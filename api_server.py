from __future__ import annotations
import os, time, socket
from pathlib import Path
from fastapi import FastAPI, Query

APP_START = time.time()
app = FastAPI(title="JKM-AI-BOT API", version="0.1.0")

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
