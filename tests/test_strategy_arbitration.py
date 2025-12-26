"""tests.test_strategy_arbitration

Step 9: Multi-strategy winner rule unit test.

winner = max(candidates, key=lambda c: (c.score, -c.priority, c.rr or 0))

Run:
    pytest -q
"""

from __future__ import annotations

from strategies.arbitration import StrategyCandidate, select_winner


def test_select_winner_by_score_then_priority_then_rr():
    # score wins first
    c1 = StrategyCandidate(strategy_id="A", score=1.10, priority=100, rr=1.0)
    c2 = StrategyCandidate(strategy_id="B", score=1.05, priority=1, rr=9.0)
    assert select_winner([c1, c2]) == c1

    # tie on score -> lower priority wins
    c3 = StrategyCandidate(strategy_id="A", score=1.00, priority=50, rr=1.0)
    c4 = StrategyCandidate(strategy_id="B", score=1.00, priority=10, rr=1.0)
    assert select_winner([c3, c4]) == c4

    # tie on score+priority -> higher rr wins
    c5 = StrategyCandidate(strategy_id="A", score=1.00, priority=50, rr=1.5)
    c6 = StrategyCandidate(strategy_id="B", score=1.00, priority=50, rr=2.0)
    assert select_winner([c5, c6]) == c6
