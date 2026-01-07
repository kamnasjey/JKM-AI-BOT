from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from auth_service import (
    create_session,
    get_user_id_for_token,
    invalidate_session,
    refresh_session,
)
from config import (
    ADMIN_USER_ID,
    PUBLIC_SUPPORT_EMAIL,
    PUBLIC_TELEGRAM_URL,
)
from trading_service import (
    get_macro_overview,
    get_str_analysis,
    get_tech_analysis,
    list_pairs,
)
from user_db import (
    add_user,
    authenticate_user,
    create_account,
    create_email_verification,
    delete_user,
    ensure_admin_account,
    get_account,
    list_users,
    verify_email_token,
    verify_email_code,
)
from user_profile import DEFAULT_PROFILE, get_profile
from scanner_service import scanner_service

from core.ops import build_health_snapshot, log_startup_banner
from core.signal_payload_public_v1 import to_public_v1, to_public_v1_from_legacy_dict
from core.signal_payload_v1 import SignalPayloadV1
from core.signals_store import get_signal_by_id_jsonl, list_signals_jsonl
from core.user_strategies_store import load_user_strategies, save_user_strategies

load_dotenv()

app = FastAPI(title="JKM Trading AI Web")

_WEB_LOGGER = logging.getLogger("JKMWebApp")

# This module lives under `apps/`, so resolve repo-root relative paths explicitly.
REPO_DIR = Path(__file__).resolve().parents[1]
BASE_DIR = REPO_DIR
DEFAULT_USER_ID = 1
ADMIN_ID_STR = str(ADMIN_USER_ID) if ADMIN_USER_ID else "admin"

@app.on_event("startup")
def startup_event():
    # Emit one-line ops banner early.
    try:
        log_startup_banner(
            _WEB_LOGGER,
            presets_dir=str(REPO_DIR / "config" / "presets"),
            notify_mode=os.getenv("NOTIFY_MODE"),
            provider=os.getenv("DATA_PROVIDER") or os.getenv("MARKET_DATA_PROVIDER"),
        )
    except Exception:
        pass

    try:
        # Task 3: Startup visibility for signal history paths
        from core.signals_store import DEFAULT_SIGNALS_PATH, DEFAULT_PUBLIC_SIGNALS_PATH
        log_kv(
            _WEB_LOGGER,
            "SIGNALS_HISTORY_CONFIG",
            signals_path=str(DEFAULT_SIGNALS_PATH),
            public_signals_path=str(DEFAULT_PUBLIC_SIGNALS_PATH),
        )
    except Exception:
        pass

    # Start the 24/7 background scanner
    scanner_service.start()
    logging.info("Web App Startup: Scanner Service Started")


@app.get("/health")
def health() -> JSONResponse:
    payload = build_health_snapshot(
        scanner=scanner_service,
        strategies_path=str(REPO_DIR / "config" / "strategies.json"),
        presets_dir=str(REPO_DIR / "config" / "presets"),
        metrics_events_path=str(REPO_DIR / "state" / "metrics_events.jsonl"),
        patch_audit_path=str(REPO_DIR / os.getenv("PATCH_AUDIT_PATH", "state/patch_audit.jsonl")),
    )
    # Exit semantics are for CLI; for HTTP we surface status in JSON only.
    return JSONResponse(payload)

@app.on_event("shutdown")
def shutdown_event():
    scanner_service.stop()
    logging.info("Web App Shutdown: Scanner Service Stopped")

CHARTBOARD_DIST_DIR = REPO_DIR / "frontend" / "dist"
if CHARTBOARD_DIST_DIR.exists():
    # Serve the built Vite/React chartboard inside the same site.
    # Note: Vite default build outputs absolute /assets URLs.
    app.mount(
        "/chartboard",
        StaticFiles(directory=str(CHARTBOARD_DIST_DIR), html=True),
        name="chartboard",
    )
    assets_dir = CHARTBOARD_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="chartboard_assets")
    vite_icon = CHARTBOARD_DIST_DIR / "vite.svg"
    if vite_icon.exists():

        @app.get("/vite.svg")
        def chartboard_vite_icon() -> FileResponse:
            return FileResponse(vite_icon)

ensure_admin_account(DEFAULT_PROFILE.copy())

# --- Scanner Endpoints ---

@app.post("/api/scan/start")
def api_scan_start(request: Request):
    account, _ = _require_account(request)
    if not account.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin required")
    scanner_service.start()
    return {"status": "Scanner started"}

@app.post("/api/scan/stop")
def api_scan_stop(request: Request):
    account, _ = _require_account(request)
    if not account.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin required")
    scanner_service.stop()
    return {"status": "Scanner stopped"}

@app.get("/api/scan/manual")
def api_scan_manual(request: Request):
    """Trigger an immediate scan pass"""
    account, _ = _require_account(request)
    # Allows valid users to trigger scan? or only admin. Let's say valid user.
    scanner_service.manual_scan()
    return {"status": "Manual scan triggered"}


class RegisterPayload(BaseModel):
    name: str
    email: EmailStr
    password: str
    telegram_handle: Optional[str] = None
    strategy_note: Optional[str] = None


class LoginPayload(BaseModel):
    email: EmailStr
    password: str


class EngineLevel(BaseModel):
    price: float
    label: Optional[str] = None


class EngineZone(BaseModel):
    priceFrom: float
    priceTo: float
    label: Optional[str] = None


class EngineAnnotationsResponse(BaseModel):
    symbol: str
    has_setup: bool
    levels: List[EngineLevel] = []
    zones: List[EngineZone] = []
    fiboZones: List[EngineZone] = []
    reasons: List[str] = []


def _extract_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    cookie_token = request.cookies.get("session_token")
    if cookie_token:
        return cookie_token
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    return None


def _get_auth_context(request: Request) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    token = _extract_token(request)
    if not token:
        return None, None
    user_id = get_user_id_for_token(token)
    if not user_id:
        return None, None
    account = get_account(user_id)
    return account, token


def _require_account(request: Request) -> Tuple[Dict[str, Any], str]:
    account, token = _get_auth_context(request)
    if not account or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Энэ үйлдлийг хийхийн тулд нэвтрэнэ үү.",
        )
    return account, token


def _resolve_user_id(request: Request, fallback: Optional[str] = None) -> str:
    account, _ = _get_auth_context(request)
    if account and account.get("user_id"):
        return str(account["user_id"])
    if fallback is not None:
        return str(fallback)
    return str(DEFAULT_USER_ID)


def _public_user(account: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "user_id": account.get("user_id"),
        "name": account.get("name"),
        "email": account.get("email"),
        "telegram_handle": account.get("telegram_handle"),
        "is_admin": bool(account.get("is_admin")),
        "email_verified": bool(account.get("email_verified")),
    }


def _build_engine_annotations_from_str(
    symbol: str, str_payload: Dict[str, Any]
) -> EngineAnnotationsResponse:
    has_setup = bool(str_payload.get("has_setup"))
    reasons = str_payload.get("reasons")
    if not isinstance(reasons, list):
        reasons = []

    setup = str_payload.get("setup")
    if not isinstance(setup, dict):
        return EngineAnnotationsResponse(
            symbol=symbol,
            has_setup=False,
            levels=[],
            zones=[],
            fiboZones=[],
            reasons=[str(r) for r in reasons],
        )

    def _num(v: Any) -> Optional[float]:
        try:
            f = float(v)
        except Exception:
            return None
        return f if f == f else None

    direction = str(setup.get("direction") or "").upper().strip()
    entry = _num(setup.get("entry"))
    sl = _num(setup.get("sl"))
    tp = _num(setup.get("tp"))
    rr = setup.get("rr")

    levels: List[EngineLevel] = []
    zones: List[EngineZone] = []
    fibo_zones: List[EngineZone] = []

    if entry is not None:
        levels.append(EngineLevel(price=entry, label=f"Entry {direction}".strip()))
    if sl is not None:
        levels.append(EngineLevel(price=sl, label="SL"))
    if tp is not None:
        rr_suffix = f" (RR {rr})" if rr is not None else ""
        levels.append(EngineLevel(price=tp, label=f"TP{rr_suffix}"))

    if entry is not None and sl is not None:
        zones.append(
            EngineZone(
                priceFrom=min(entry, sl),
                priceTo=max(entry, sl),
                label="Risk zone",
            )
        )

    if entry is not None and tp is not None:
        fibo_zones.append(
            EngineZone(
                priceFrom=min(entry, tp),
                priceTo=max(entry, tp),
                label="Target zone",
            )
        )

    return EngineAnnotationsResponse(
        symbol=symbol,
        has_setup=has_setup,
        levels=levels,
        zones=zones,
        fiboZones=fibo_zones,
        reasons=[str(r) for r in reasons],
    )


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Serve the single page trader dashboard."""
    index_path = REPO_DIR / "apps" / "static" / "index.html"
    if not index_path.exists():
        return HTMLResponse(f"index.html олдсонгүй: {index_path}", status_code=500)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/favicon.ico")
def favicon() -> Response:
    """Avoid noisy 404s for favicon requests (optional)."""
    return Response(status_code=204)


@app.post("/api/auth/register")
def api_auth_register(request: Request, payload: RegisterPayload) -> Dict[str, Any]:
    profile = DEFAULT_PROFILE.copy()
    if payload.strategy_note:
        profile["note"] = payload.strategy_note.strip()
    try:
        account = create_account(
            name=payload.name.strip(),
            email=str(payload.email),
            password=payload.password,
            telegram_handle=(payload.telegram_handle or "").strip(),
            profile=profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Create verification token and send email (best-effort).
    code = create_email_verification(email=str(payload.email))
    if not code:
        # If already verified (shouldn't happen for new accounts) or cannot create token.
        return {
            "status": "created",
            "message": "Аккаунт үүсгэлээ.",
        }

    public_base = (os.getenv("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")
    verify_url = f"{public_base}/api/auth/verify-email?token={code}"
    try:
        from services.email_service import send_verification_email

        send_verification_email(to_email=str(payload.email), code=code, verify_url=verify_url)
    except Exception as exc:
        # Dev-friendly fallback: optionally show the verify URL without sending email.
        show_url = os.getenv("DEV_SHOW_VERIFY_URL", "false").strip().lower() in ("1", "true", "yes", "y")
        if show_url:
            logging.getLogger(__name__).warning(
                "Email send failed (DEV_SHOW_VERIFY_URL=true). Verify URL: %s | error=%s",
                verify_url,
                str(exc),
            )
            return {
                "status": "verification_pending",
                "message": "SMTP тохируулаагүй тул verify имэйл явуулж чадсангүй. DEV горим дээр verify холбоосыг харууллаа.",
                "dev_verify_url": verify_url,
                "dev_code": code,
            }
        # Production/default: don't leak SMTP internals; keep a friendly message.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Бүртгэл үүссэн боловч баталгаажуулах имэйл илгээж чадсангүй. SMTP тохиргоогоо шалгана уу.",
        )

    return {
        "status": "verification_sent",
        "message": "Имэйл рүү 6 оронтой баталгаажуулах код явууллаа. Кодоо оруулаад verify хийнэ үү.",
    }


class VerifyCodePayload(BaseModel):
    email: EmailStr
    code: str


@app.post("/api/auth/verify-code")
def api_auth_verify_code(payload: VerifyCodePayload) -> Dict[str, Any]:
    account = verify_email_code(email=str(payload.email), code=str(payload.code))
    if not account:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Код буруу эсвэл хугацаа дууссан байна.",
        )
    token = create_session(account["user_id"])
    return {"token": token, "user": _public_user(account)}


@app.get("/api/auth/verify-email", response_class=HTMLResponse)
def api_auth_verify_email(token: str) -> HTMLResponse:
    # Backward/optional: verify via link (token currently equals the 6-digit code).
    account = verify_email_token(token=token)
    if not account:
        return HTMLResponse(
            "<h3>Email verification failed</h3><p>Link хүчингүй эсвэл хугацаа дууссан байна. Verify кодоо ашиглана уу (эсвэл resend хий).</p>",
            status_code=400,
        )

    session_token = create_session(account["user_id"])
    # Store token in localStorage (matches static/index.html TOKEN_STORAGE_KEY) then redirect to home.
    html = f"""
<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Email Verified</title></head>
<body style='font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; padding:24px;'>
  <h3>Email баталгаажлаа ✅</h3>
  <p>Самбар руу шилжиж байна...</p>
  <script>
    try {{
      localStorage.setItem('jkm_ai_session_v1', {session_token!r});
    }} catch (e) {{}}
    window.location.href = '/#auth';
  </script>
</body></html>
"""
    return HTMLResponse(html)


@app.post("/api/auth/login")
def api_auth_login(payload: LoginPayload) -> Dict[str, Any]:
    account = authenticate_user(str(payload.email), payload.password)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Имэйл эсвэл нууц үг буруу.",
        )

    token = create_session(account["user_id"])
    return {"token": token, "user": _public_user(account)}


@app.post("/api/auth/resend-verification")
def api_auth_resend_verification(payload: LoginPayload, request: Request) -> Dict[str, Any]:
    # Reuse LoginPayload for email field only (password ignored).
    email = str(payload.email)
    code = create_email_verification(email=email)
    if not code:
        return {"status": "ok", "message": "Хэрвээ аккаунт байгаа бөгөөд verify хийгдээгүй бол имэйл явуулна."}
    public_base = (os.getenv("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")
    verify_url = f"{public_base}/api/auth/verify-email?token={code}"
    try:
        from services.email_service import send_verification_email

        send_verification_email(to_email=email, code=code, verify_url=verify_url)
    except Exception:
        show_url = os.getenv("DEV_SHOW_VERIFY_URL", "false").strip().lower() in ("1", "true", "yes", "y")
        if show_url:
            logging.getLogger(__name__).warning(
                "Resend verification email failed (DEV_SHOW_VERIFY_URL=true). Verify URL: %s",
                verify_url,
            )
            return {"status": "ok", "message": "DEV горим: verify мэдээллийг буцаалаа.", "dev_verify_url": verify_url, "dev_code": code}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verify имэйл дахин илгээж чадсангүй. SMTP тохиргоогоо шалгана уу.",
        )
    return {"status": "ok", "message": "Verify имэйл дахин явууллаа. Inbox/Spam шалгана уу."}


@app.get("/api/auth/me")
def api_auth_me(request: Request) -> Dict[str, Any]:
    account, token = _require_account(request)
    refresh_session(token)
    return {"user": _public_user(account)}


@app.post("/api/auth/logout")
def api_auth_logout(request: Request) -> Dict[str, str]:
    token = _extract_token(request)
    if token:
        invalidate_session(token)
    return {"status": "logged_out"}


@app.get("/api/contact")
def api_contact() -> Dict[str, str]:
    return {
        "telegram_url": PUBLIC_TELEGRAM_URL,
        "support_email": PUBLIC_SUPPORT_EMAIL,
    }


@app.get("/api/status")
def api_status() -> Dict[str, str]:
    return {"status": "ok", "app": app.title}


@app.get("/api/log")
def api_log() -> JSONResponse:
    log_path = REPO_DIR / "logs" / "app.log"
    if not log_path.exists():
        return JSONResponse({"log": "Лог файл олдсонгүй."}, status_code=404)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return JSONResponse({"log": lines[-100:]})


@app.get("/api/pairs")
def api_pairs() -> Any:
    return list_pairs()


@app.get("/api/str-analyze")
def api_str_analyze(request: Request, symbol: str) -> Any:
    account, _ = _require_account(request)
    return get_str_analysis(user_id=str(account["user_id"]), pair=symbol)


@app.get("/api/chart/annotations", response_model=EngineAnnotationsResponse)
def api_chart_annotations(request: Request, symbol: str) -> EngineAnnotationsResponse:
    account, _ = _require_account(request)
    payload = get_str_analysis(user_id=str(account["user_id"]), pair=symbol)
    return _build_engine_annotations_from_str(symbol, payload)


@app.get("/api/tech-analyze")
def api_tech_analyze(request: Request, symbol: str) -> Any:
    _require_account(request)
    return get_tech_analysis(symbol)


@app.get("/api/macro")
def api_macro(request: Request) -> Any:
    _require_account(request)
    return get_macro_overview()


@app.get("/api/profile")
def api_profile(request: Request) -> Any:
    account, _ = _require_account(request)
    return get_profile(str(account["user_id"]))


@app.get("/api/strategies")
def api_get_strategies(request: Request) -> Any:
    account, _ = _require_account(request)
    user_id = str(account["user_id"])
    return {"schema_version": 1, "user_id": user_id, "strategies": load_user_strategies(user_id)}


@app.put("/api/strategies")
async def api_put_strategies(request: Request) -> Any:
    account, _ = _require_account(request)
    user_id = str(account["user_id"])

    try:
        body = await request.json()
    except Exception:
        body = None

    raw_items: Any
    if isinstance(body, dict) and "strategies" in body:
        raw_items = body.get("strategies")
    else:
        raw_items = body

    res = save_user_strategies(user_id, raw_items)
    if not res.get("strategies") and res.get("warnings"):
        raise HTTPException(status_code=400, detail=res)
    return res


@app.get("/api/metrics")
def api_metrics(request: Request) -> Any:
    account, _ = _require_account(request)
    user_id = str(account["user_id"])
    try:
        from signals_tracker import evaluate_pending_signals_for_user, get_user_metrics

        # Keep metrics fresh even if scanner is paused.
        evaluate_pending_signals_for_user(user_id=user_id)
        return get_user_metrics(user_id)
    except Exception as e:
        return {"error": str(e), "user_id": user_id}


@app.get("/api/signals")
def api_signals(request: Request, limit: int = 50, symbol: Optional[str] = None, user_id: Optional[str] = None) -> Any:
    account, _ = _require_account(request)
    is_admin = bool(account.get("is_admin"))

    effective_user_id = str(account.get("user_id"))
    if is_admin and user_id:
        effective_user_id = str(user_id)

    # Task 4: List from public history if available (preferred for UI)
    from core.signals_store import list_public_signals_jsonl
    
    # Try public history (signals.jsonl) first
    items = list_public_signals_jsonl(
        user_id=effective_user_id,
        limit=limit,
        symbol=symbol,
        include_all_users=is_admin and (user_id is None),
    )
    
    # Fallback to legacy if public returns empty (and we suspect missing file, though existing logic returns [] on missing file)
    # Actually, `list_public_signals_jsonl` returns [] if file missing. 
    # To keep backward compat fully, we can check if items is empty, try legacy.
    # But if real history IS empty, this double-fetch is harmless.
    if not items:
         items = list_signals_jsonl(
            user_id=effective_user_id,
            limit=limit,
            symbol=symbol,
            include_all_users=is_admin and (user_id is None),
        )

    out: List[Dict[str, Any]] = []
    for item in items:
        try:
            # If item is already public format (likely), just use it. 
            # If it's legacy, convert.
            # We can detect by checking if it matches Public V1 schema or has specific keys.
            if "legacy" in item or "engine_annotations" in item:
                 # Already public or rich payload
                 out.append(item)
            else:
                # Convert legacy
                v1 = SignalPayloadV1.model_validate(item)
                pub = to_public_v1(v1).model_dump(mode="json")
                pub["legacy"] = item
                out.append(pub)
        except Exception:
            continue

    return out


@app.get("/api/signals/{signal_id}")
def api_signal_detail(request: Request, signal_id: str) -> Any:
    account, _ = _require_account(request)
    is_admin = bool(account.get("is_admin"))
    effective_user_id = str(account.get("user_id"))

    # Task 4: Signal detail from public history first
    from core.signals_store import get_public_signal_by_id_jsonl

    payload = get_public_signal_by_id_jsonl(
        user_id=effective_user_id,
        signal_id=signal_id,
        include_all_users=is_admin,
    )
    
    if not payload:
        # Fallback to legacy
        payload = get_signal_by_id_jsonl(
            user_id=effective_user_id,
            signal_id=signal_id,
            include_all_users=is_admin,
        )

    if not payload:
        raise HTTPException(status_code=404, detail="Signal not found")
        
    try:
        # If already public format
        if "engine_annotations" in payload:
             # Best effort norm
             return payload
             
        v1 = SignalPayloadV1.model_validate(payload)
        pub = to_public_v1(v1).model_dump(mode="json")
        pub["legacy"] = payload
        return pub
    except Exception:
        # Last resort: treat as legacy dict and wrap
        try:
             # If it fails validation but is not None, wrap it safely
             pub = to_public_v1_from_legacy_dict(payload).model_dump(mode="json")
             pub["legacy"] = payload
             return pub
        except Exception:
             # Should practically never happen if payload is dict
             return payload


@app.get("/api/signal/{signal_id}")
def api_signal_detail_alias(request: Request, signal_id: str) -> Any:
    # Alias for backward/forward compatibility with clients expecting singular path.
    return api_signal_detail(request, signal_id)


@app.get("/api/detectors")
def api_detectors(request: Request, include_docs: int = 0) -> Any:
    _require_account(request)
    try:
        from detectors.registry import DETECTOR_REGISTRY

        names = sorted(list(DETECTOR_REGISTRY.keys()))
        if not include_docs:
            return {"detectors": names}

        catalog: List[Dict[str, Any]] = []
        for name in names:
            cls = DETECTOR_REGISTRY.get(name)
            if cls is None:
                continue

            doc = getattr(cls, "doc", "")
            params_schema = getattr(cls, "params_schema", None)
            examples = getattr(cls, "examples", None)

            catalog.append(
                {
                    "name": name,
                    "doc": str(doc) if doc is not None else "",
                    "params_schema": dict(params_schema) if isinstance(params_schema, dict) else {},
                    "examples": [dict(x) for x in examples if isinstance(x, dict)] if isinstance(examples, list) else [],
                }
            )

        return {"detectors": catalog}
    except Exception:
        return {"detectors": []}


@app.get("/api/profiles")
def api_profiles(request: Request) -> Any:
    account, _ = _require_account(request)
    if not account.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Зөвхөн админ хэрэглэгч энэ жагсаалтыг харах эрхтэй.",
        )
    return list_users()


@app.put("/api/profile")
async def api_update_profile(request: Request) -> Dict[str, Any]:
    """
    Two modes:
    1. {"command": "STR: ..."} -> parses text
    2. {"profile": {...}} -> direct update
    """
    account, _ = _require_account(request)
    user_id = str(account["user_id"])
    payload = await request.json()
    
    if "command" in payload:
        # Text parsing mode
        from user_profile import set_profile_from_text
        msg = set_profile_from_text(user_id, payload["command"])
        # Fetch updated profile to return
        from user_profile import get_profile
        return {
            "status": "parsed",
            "message": msg,
            "profile": get_profile(user_id)
        }
    
    # Direct JSON mode
    profile_payload = payload.get("profile")
    if isinstance(profile_payload, dict):
        from services.models import UserProfile
        from user_db import add_user, get_user
        
        existing = get_user(user_id) or {}
        merged = dict(existing)
        merged.update(profile_payload)

        # Normalize timezone if provided
        if "tz_offset_hours" in merged and merged.get("tz_offset_hours") is not None:
            try:
                tz_h = int(str(merged.get("tz_offset_hours")).strip())
            except Exception:
                tz_h = 0
            tz_h = max(-12, min(14, tz_h))
            merged["tz_offset_hours"] = tz_h

        # Validate core profile fields (extra keys allowed in DB)
        try:
            UserProfile.parse_obj(merged)
        except Exception:
            # If validation fails, still keep merged storage behavior stable
            pass

        name = payload.get("name") or merged.get("name") or existing.get("name") or f"User {user_id}"
        merged["name"] = name
        add_user(user_id, name, merged)
        return {"status": "saved", "user_id": user_id, "profile": merged}
        
    return {"status": "error", "message": "No 'command' or 'profile' provided"}


@app.delete("/api/profile")
def api_delete_profile(request: Request, user_id: str) -> Any:
    # Admin manual deletion only.
    account, _ = _require_account(request)
    if not account.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Зөвхөн админ хэрэглэгч устгах эрхтэй.",
        )

    # Safety: never allow deleting the currently authenticated account.
    if str(account.get("user_id")) == str(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Өөрийн (нэвтэрсэн) аккаунтыг устгахыг хориглосон.",
        )

    delete_user(user_id)
    return {"status": "Устгагдсан", "user_id": user_id}



# --- Market Data API ---


def _get_market_candles_from_cache(symbol: str, tf: str = "5m", limit: int = 500) -> List[Dict[str, Any]]:
    sym = str(symbol or "").upper().strip()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")

    tf_norm = str(tf or "5m").strip() or "5m"

    from market_data_cache import market_cache

    candles = market_cache.get_candles(sym)

    # Resample if needed (MVP supports 5m native, others derived)
    if tf_norm.lower() != "5m":
        from resample_5m import resample

        candles = resample(candles, tf_norm)

    if limit and int(limit) > 0:
        candles = candles[-int(limit) :]

    return candles

@app.get("/api/markets/symbols")
def api_markets_symbols() -> List[str]:
    """Returns list of active symbols from the cache/watchlist."""
    from market_data_cache import market_cache
    from watchlist_union import get_union_watchlist
    # We prefer the union watchlist as it drives the ingestor
    return get_union_watchlist(max_per_user=5)


@app.get("/api/candles")
def api_candles(symbol: str, tf: str = "5m", limit: int = 500) -> List[Dict[str, Any]]:
    """Compatibility endpoint for clients expecting query-param candles."""
    return _get_market_candles_from_cache(symbol=symbol, tf=tf, limit=limit)

@app.get("/api/markets/{symbol}/candles")
def api_markets_candles(symbol: str, tf: str = "5m", limit: int = 500) -> List[Dict[str, Any]]:
    """Get history candles from cache."""
    return _get_market_candles_from_cache(symbol=symbol, tf=tf, limit=limit)

from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/markets/{symbol}")
async def ws_markets_symbol(websocket: WebSocket, symbol: str, tf: str = "5m"):
    await websocket.accept()
    symbol = symbol.upper()
    
    from market_data_cache import market_cache
    import asyncio
    
    last_ts = None
    
    try:
        while True:
            # 1. Check for new data in cache
            # If tf is 5m, we can use efficient check.
            # For derived TFs, efficient check is harder, we might just re-resample 
            # or check if underlying 5m changed.
            
            # Simple polling for MVP: 1s
            current_last_ts = market_cache.get_last_timestamp(symbol)
            
            if current_last_ts and (last_ts is None or current_last_ts > last_ts):
                # Send update
                # Get the latest candle(s). 
                # If we are strictly sending updates, maybe just the last one?
                # TradingView charts often want the last candle modification or a new one.
                
                all_candles = market_cache.get_candles(symbol)
                if tf.lower() != "5m":
                    from resample_5m import resample
                    candles = resample(all_candles, tf)
                else:
                    candles = all_candles
                
                if candles:
                    latest = candles[-1]
                    # We might need to send more if resampling changed previous candle?
                    # For now just send latest.
                    
                    # Convert datetime to int timestamp (epoch) for JS
                    # JS expects ms or seconds. LW charts usually seconds.
                    
                    def _serialize(c):
                        ts = c['time']
                        if hasattr(ts, 'timestamp'):
                            ts = int(ts.timestamp())
                        return {
                            'time': ts,
                            'open': c['open'],
                            'high': c['high'],
                            'low': c['low'],
                            'close': c['close']
                        }
                    
                    await websocket.send_json(_serialize(latest))
                    last_ts = current_last_ts
            
            await asyncio.sleep(1)
            
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logging.error(f"WS Error {symbol}: {e}")

