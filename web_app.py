from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from trading_service import (
    list_pairs,
    get_str_analysis,
    get_tech_analysis,
    get_macro_overview,
)

load_dotenv()  # ← .env-ээс IG, EPIC бүх хувьсагчдыг уншина

app = FastAPI(title="JKM Trading AI Web")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_USER_ID = 1



@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = BASE_DIR / "static" / "index.html"
    if not index_path.exists():
        # Алдаа гарвал яг хаана хайж байгааг browser дээр харуулна
        return HTMLResponse(
            f"index.html олдсонгүй: {index_path}", status_code=500
        )
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/pairs")
def api_pairs():
    return list_pairs()


@app.get("/api/str-analyze")
def api_str_analyze(symbol: str, user_id: int = DEFAULT_USER_ID):
    return get_str_analysis(user_id=user_id, pair=symbol)


@app.get("/api/tech-analyze")
def api_tech_analyze(symbol: str):
    return get_tech_analysis(symbol)


@app.get("/api/macro")
def api_macro():
    return get_macro_overview()
