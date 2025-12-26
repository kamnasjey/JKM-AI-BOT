"""scripts.health_report

CLI ops snapshot.

Usage:
  python scripts/health_report.py

Exits:
  0 if status == "ok"
  1 otherwise
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from core.ops import build_health_snapshot


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Print ops health snapshot JSON.")
    p.add_argument("--strategies_path", type=str, default="config/strategies.json")
    p.add_argument("--presets_dir", type=str, default="config/presets")
    p.add_argument("--metrics_events_path", type=str, default="state/metrics_events.jsonl")
    p.add_argument(
        "--patch_audit_path",
        type=str,
        default=os.getenv("PATCH_AUDIT_PATH", "state/patch_audit.jsonl"),
    )
    args = p.parse_args(argv)

    # Resolve paths relative to repo root (script lives under scripts/).
    repo_dir = Path(__file__).resolve().parents[1]

    payload = build_health_snapshot(
        scanner=None,
        strategies_path=str(repo_dir / args.strategies_path),
        presets_dir=str(repo_dir / args.presets_dir),
        metrics_events_path=str(repo_dir / args.metrics_events_path),
        patch_audit_path=str(repo_dir / args.patch_audit_path),
    )

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    status = str(payload.get("status") or "error").strip().lower()
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
