from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class Finding:
    path: Path
    line_no: int
    line: str
    reason: str


_SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


_STATE_LITERAL_OPEN_RE = re.compile(
    r"open\(\s*[rRuUfF]?[\"']state/[^\"']+[\"']\s*,\s*[\"'](?P<mode>[wa])[\"']",
)
_STATE_LITERAL_WRITE_TEXT_RE = re.compile(
    r"Path\(\s*[\"']state/[^\"']+[\"']\s*\)\.write_text\(",
)

# Heuristic: open(..., "w"/"a") near a state path mention.
_OPEN_WA_RE = re.compile(r"open\(.*?,\s*[\"'](?P<mode>[wa])[\"']", re.IGNORECASE)


def _iter_py_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        yield p


def _is_test_path(path: Path) -> bool:
    parts = {x.lower() for x in path.parts}
    if "tests" in parts:
        return True
    name = path.name.lower()
    return name.startswith("test_") or name.endswith("_test.py")


def audit_repo(root: Path) -> List[Finding]:
    findings: List[Finding] = []

    for path in _iter_py_files(root):
        if path.name == "audit_atomic_state_writes.py":
            continue
        # Tests can use direct writes; they are not production state.
        if _is_test_path(path):
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        lines = text.splitlines()
        for idx, line in enumerate(lines, start=1):
            if _STATE_LITERAL_OPEN_RE.search(line):
                findings.append(
                    Finding(
                        path=path,
                        line_no=idx,
                        line=line.strip(),
                        reason="DIRECT_STATE_OPEN_WA",
                    )
                )
                continue
            if _STATE_LITERAL_WRITE_TEXT_RE.search(line):
                findings.append(
                    Finding(
                        path=path,
                        line_no=idx,
                        line=line.strip(),
                        reason="DIRECT_STATE_WRITE_TEXT",
                    )
                )
                continue

            m = _OPEN_WA_RE.search(line)
            if m and "state/" in line:
                findings.append(
                    Finding(
                        path=path,
                        line_no=idx,
                        line=line.strip(),
                        reason="OPEN_WA_NEAR_STATE_LITERAL",
                    )
                )

        # Heuristic across small windows: open(..., w/a) within 6 lines of a state/ mention.
        for i in range(len(lines)):
            window = "\n".join(lines[i : i + 7])
            if "state/" not in window:
                continue
            for j, win_line in enumerate(lines[i : i + 7], start=0):
                if _OPEN_WA_RE.search(win_line):
                    findings.append(
                        Finding(
                            path=path,
                            line_no=i + j + 1,
                            line=win_line.strip(),
                            reason="OPEN_WA_NEAR_STATE_CONTEXT",
                        )
                    )

    # Deduplicate
    uniq = {(f.path, f.line_no, f.reason): f for f in findings}
    out = list(uniq.values())
    out.sort(key=lambda x: (str(x.path).lower(), x.line_no, x.reason))
    return out


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings = audit_repo(root)

    if not findings:
        print("OK: no suspicious non-atomic state writes found")
        return 0

    print("FAIL: suspicious non-atomic state writes found")
    for f in findings:
        rel = f.path.relative_to(root)
        print(f"{rel}:{f.line_no}: {f.reason}: {f.line}")

    print("\nExpected: use core.atomic_io.atomic_write_text / atomic_append_jsonl_via_replace for state/*.json* writes")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
