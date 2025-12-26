from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> int:
    p = subprocess.run(cmd)
    return int(p.returncode)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]

    # 0) Audit for accidental non-atomic writes.
    rc = _run([sys.executable, str(repo / "scripts" / "audit_atomic_state_writes.py")])
    if rc != 0:
        return rc

    # 1) Syntax/import check.
    rc = _run([sys.executable, "-m", "compileall", "-q", str(repo)])
    if rc != 0:
        return rc

    # 2) Test suite.
    rc = _run([sys.executable, "-m", "pytest", "-q"])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
