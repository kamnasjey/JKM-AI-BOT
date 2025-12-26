"""core.models

Lightweight dataclasses shared by the indicator-free engine.

This module is intentionally dependency-free so it can be imported from core/
without pulling service/web layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


@dataclass
class DetectorHit:
    detector: str
    direction: Literal["BUY", "SELL"]
    score_contrib: float
    family: str
    reasons: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    # Backward compatible: some older code paths used an `ok` flag.
    ok: bool = True


@dataclass
class CombineResult:
    ok: bool
    direction: Optional[Literal["BUY", "SELL"]] = None
    score: float = 0.0
    fail_reason: Optional[str] = None  # SCORE_BELOW_MIN | CONFLICT_SCORE
    evidence: Dict[str, Any] = field(default_factory=dict)
