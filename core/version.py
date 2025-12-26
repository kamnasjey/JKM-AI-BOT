"""core.version

Central, importable version + schema constants for ops/debug.

Keep this file dependency-free (stdlib only).
"""

from __future__ import annotations

import os
from typing import List


# Human version (semver-ish). Bump intentionally.
APP_VERSION: str = os.getenv("APP_VERSION", "0.6.0").strip() or "0.6.0"

# Optional git sha injected by CI/CD (or Render-like env vars).
GIT_SHA: str = (
    os.getenv("GIT_SHA")
    or os.getenv("RENDER_GIT_COMMIT")
    or os.getenv("SOURCE_VERSION")
    or "NA"
).strip() or "NA"

# Strategy pack schema versions supported by this runtime.
STRATEGY_SCHEMA_VERSION_SUPPORTED: List[int] = [1]

# Explain payload schema version (Explain API v1).
EXPLAIN_SCHEMA_VERSION: int = 1

# Metrics event schema version.
METRICS_EVENT_SCHEMA_VERSION: int = 1

# DetectorResult contract schema version (engines.detectors).
DETECTOR_RESULT_SCHEMA_VERSION: int = 2
