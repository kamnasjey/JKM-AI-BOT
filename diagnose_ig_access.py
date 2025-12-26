"""Diagnose IG credentials + market-data access using existing .env.

This script:
- Logs in via IGClient.from_env()
- Calls /accounts to confirm auth works
- Searches /markets for a few terms to find EPICs
- Tries /prices for a handful of EPICs and prints only status codes

It avoids printing secrets (API key, CST, X-SECURITY-TOKEN).
"""

from __future__ import annotations

import argparse
import os
from typing import Iterable, List, Optional, Tuple

from ig_client import IGClient, ig_call_source


def _safe_print(text: str) -> None:
    redacted = text
    for key_name in ("IG_API_KEY", "IG_DEMO_API_KEY"):
        secret = os.getenv(key_name, "")
        if secret:
            redacted = redacted.replace(secret, "***")
    print(redacted)


def _get(url: str, headers: dict, params: Optional[dict] = None) -> Tuple[int, str]:
    # Return (status_code, short_body)
    resp = ig.session.get(url, headers=headers, params=params)
    body = resp.text or ""
    body_short = body[:400].replace("\n", " ")
    return resp.status_code, body_short


def search_markets(term: str, *, limit: int = 8) -> List[str]:
    url = f"{ig.base_url}/markets"
    headers = ig._auth_headers(version="1")
    status, body_short = _get(url, headers, params={"searchTerm": term})
    if status != 200:
        _safe_print(f"SEARCH term={term} status={status} body={body_short}")
        return []

    data = ig.session.get(url, headers=headers, params={"searchTerm": term}).json()
    markets = data.get("markets", []) or []
    epics: List[str] = []
    for m in markets[:limit]:
        epic = m.get("epic")
        name = m.get("instrumentName")
        status_m = m.get("marketStatus")
        expiry = m.get("expiry")
        if epic:
            epics.append(epic)
        _safe_print(f"FOUND {term}: {epic} | {name} | {expiry} | {status_m}")
    return epics


def try_prices(epic: str) -> None:
    url = f"{ig.base_url}/prices/{epic}"
    headers = ig._auth_headers(version="3")
    # small request
    params = {"resolution": "MINUTE_5", "max": "10", "pageSize": "10"}
    status, body_short = _get(url, headers, params=params)
    if status == 200:
        _safe_print(f"PRICES OK {epic} (200)")
    else:
        _safe_print(f"PRICES FAIL {epic} status={status} body={body_short}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Diagnose IG credentials + market-data access.")
    parser.add_argument("--demo", action="store_true", help="Force demo mode (overrides IG_IS_DEMO).")
    parser.add_argument("--live", action="store_true", help="Force live mode (overrides IG_IS_DEMO).")
    args = parser.parse_args()

    if args.demo and args.live:
        raise SystemExit("Choose only one of --demo or --live")

    is_demo = True if args.demo else False if args.live else None

    with ig_call_source("diagnostic"):
        ig = IGClient.from_env(is_demo=is_demo)
    _safe_print(f"[IG] mode={'DEMO' if ig.is_demo else 'LIVE'}")

    # Basic auth check: /accounts
    accounts_url = f"{ig.base_url}/accounts"
    accounts_headers = ig._auth_headers(version="1")
    status, body_short = _get(accounts_url, accounts_headers)
    _safe_print(f"ACCOUNTS status={status} body={body_short}")

    terms = ["EURUSD", "Gold", "XAU", "BTC", "Bitcoin"]
    all_epics: List[str] = []
    for term in terms:
        with ig_call_source("diagnostic"):
            all_epics.extend(search_markets(term))

    # Add common epics used by the bot mapping
    candidates = [
        "CS.D.EURUSD.MINI.IP",
        "CS.D.CFDGOLD.CFDGC.IP",
    ]

    # Try prices for a small unique set
    uniq: List[str] = []
    for e in (candidates + all_epics):
        if e and e not in uniq:
            uniq.append(e)
        if len(uniq) >= 10:
            break

    for epic in uniq:
        with ig_call_source("diagnostic"):
            try_prices(epic)
