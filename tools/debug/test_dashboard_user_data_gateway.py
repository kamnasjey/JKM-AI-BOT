from __future__ import annotations

import json
import os
from typing import Any, Dict

import httpx


def _env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise RuntimeError(f"Missing env: {name}")
    return v


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "x-internal-api-key": api_key,
        "accept": "application/json",
        "content-type": "application/json",
    }


def main() -> None:
    base = _env("DASHBOARD_USER_DATA_URL").rstrip("/")
    key = _env("DASHBOARD_INTERNAL_API_KEY")

    print("=== Dashboard User-Data Gateway Debug ===")
    print(f"base_url: {base}")
    print(f"api_key: {'*' * 8} (len={len(key)})")

    with httpx.Client(timeout=8.0) as client:
        # 1) Health
        health_url = f"{base}/api/internal/user-data/health"
        r = client.get(health_url, headers=_headers(key))
        print("\n[HEALTH]", r.status_code)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))

        # 2) Users
        users_url = f"{base}/api/internal/user-data/users"
        r = client.get(users_url, headers=_headers(key))
        print("\n[USERS]", r.status_code)
        data = r.json()
        print(f"count: {data.get('count')}\n")
        users = data.get("users")

        sample_user_id = None
        if isinstance(users, list) and users:
            for u in users:
                if isinstance(u, dict) and u.get("user_id"):
                    sample_user_id = str(u["user_id"])
                    break

        if not sample_user_id:
            print("No paid users returned; cannot test per-user endpoints.")
            return

        # 3) User prefs
        prefs_url = f"{base}/api/internal/user-data/users/{sample_user_id}"
        r = client.get(prefs_url, headers=_headers(key))
        print("\n[USER PREFS]", r.status_code, "user_id=", sample_user_id)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))

        # 4) Strategies
        strat_url = f"{base}/api/internal/user-data/strategies/{sample_user_id}"
        r = client.get(strat_url, headers=_headers(key))
        print("\n[STRATEGIES]", r.status_code, "user_id=", sample_user_id)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
