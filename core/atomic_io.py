from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically write text to `path` via temp file + os.replace.

    Writes the temp file in the same directory to keep `os.replace` atomic.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with open(tmp_path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, path)


def atomic_append_jsonl_via_replace(path: Path, line: str) -> None:
    """Append one JSONL line by rewrite + atomic replace.

    This reads current content (if any), appends `line + "\n"` (ensuring exactly
    one trailing newline), then writes the full content atomically.
    """

    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = ""

    to_write = existing + line.rstrip("\n") + "\n"
    atomic_write_text(path, to_write)
