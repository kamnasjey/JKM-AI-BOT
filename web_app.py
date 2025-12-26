"""Backward-compatible entrypoint for uvicorn.

Keep `uvicorn web_app:app` working after codebase re-org.
The canonical FastAPI app now lives in `apps.web_app`.
"""

from apps.web_app import app  # re-export

__all__ = ["app"]

