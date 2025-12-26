from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class StrategyCandidate:
    strategy_id: str
    score: float
    priority: int
    rr: float


def select_winner(candidates: Iterable[StrategyCandidate]) -> Optional[StrategyCandidate]:
    items = list(candidates)
    if not items:
        return None

    def _key(c: StrategyCandidate):
        return (float(c.score), -int(c.priority), float(c.rr or 0.0))

    return max(items, key=_key)
