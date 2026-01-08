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
    state_dir = Path(os.getenv("STATE_DIR") or "/app/state")
    writable = _ensure_writable_dir(state_dir)

    signals_file = state_dir / "signals.jsonl"
    signals_exists = signals_file.exists()
    signals_lines_estimate = _estimate_lines_fast(signals_file) if signals_exists else 0
    return {
        "ok": True,
        "ts": int(time.time()),
        "uptime_s": int(time.time() - APP_START),
        "hostname": socket.gethostname(),
        "provider_configured": bool(massive_key),
        "state_dir": str(state_dir),
        "state_writable": writable,
        "signals_file_exists": bool(signals_exists),
        "signals_lines_estimate": int(signals_lines_estimate),
        "cache": {"ready": False, "note": "placeholder"},
        "db": {"ready": False, "note": "placeholder"},
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
