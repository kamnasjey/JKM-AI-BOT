# core/rr_filter.py

from risk import calc_rr

# rr_filter.py
"""
Filtering logic for reward:risk ratio and signal scoring.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ScoredSignal:
    """Signal with calculated score for ranking."""
    
    signal: any  # DetectorSignal type
    score: float
    confluence_count: int = 1  # How many detectors agree


def filter_by_rr(setup, min_rr: float = 2.0) -> bool:
    """
    Simple RR filter.
    Returns True if setup passes RR threshold.
    """
    if setup is None:
        return False
    return setup.rr >= min_rr


def score_and_rank_signals(
    signals: List,  # List[DetectorSignal]
    min_rr: float = 2.0,
) -> List[ScoredSignal]:
    """
    Score and rank all detector signals.
    
    Scoring criteria:
    1. RR ratio (higher is better)
    2. Signal strength from detector
    3. Confluence (multiple detectors on same pair/direction)
    
    Args:
        signals: List of DetectorSignal objects
        min_rr: Minimum RR threshold
        
    Returns:
        Sorted list of ScoredSignal (best first)
    """
    if not signals:
        return []

    # Ignore non-tradable annotations
    trade_signals = [s for s in signals if getattr(s, "kind", "signal") == "signal"]
    if not trade_signals:
        return []
    
    # Filter by min RR first
    valid_signals = [s for s in trade_signals if s.rr >= min_rr]
    
    if not valid_signals:
        return []
    
    # Build confluence map: (pair, direction) -> list of signals
    confluence_map = {}
    for sig in valid_signals:
        key = (sig.pair, sig.direction)
        if key not in confluence_map:
            confluence_map[key] = []
        confluence_map[key].append(sig)
    
    # Score each signal
    scored = []
    for sig in valid_signals:
        key = (sig.pair, sig.direction)
        confluence_count = len(confluence_map[key])
        
        # Calculate score
        # - Base: RR ratio (normalized to 0-1 range, assuming max RR ~10)
        # - Strength: detector strength (0-1)
        # - Confluence bonus: +0.1 per additional detector
        rr_score = min(sig.rr / 10.0, 1.0) * 0.5  # 50% weight
        strength_score = sig.strength * 0.3  # 30% weight
        confluence_bonus = (confluence_count - 1) * 0.1  # 20% weight max
        
        total_score = rr_score + strength_score + confluence_bonus
        
        scored.append(ScoredSignal(
            signal=sig,
            score=total_score,
            confluence_count=confluence_count,
        ))
    
    # Sort by score (descending)
    scored.sort(key=lambda x: x.score, reverse=True)
    
    return scored
