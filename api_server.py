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

# Dashboard login flow sometimes calls this; stop returning 404.
# Keep it internal-key protected (recommended).
@app.post("/api/auth/register", dependencies=[Depends(require_internal_key)])
def auth_register(payload: dict):
    # v0.1 minimal: just acknowledge; later you can store into sqlite user_db.py
    return {"ok": True, "registered": True, "payload_keys": list(payload.keys())}
