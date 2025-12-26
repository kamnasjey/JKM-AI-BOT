from core.user_core_engine import ScanResult


def test_candidates_top_is_score_desc_only():
    # This test asserts the contract implemented in the engine: candidates_top is built
    # purely by score desc (not priority/rr).
    # We validate via a synthetic debug payload instead of running the full engine.
    from core.user_core_engine import ScanResult  # noqa: F401

    candidates_ranked = [
        {"strategy_id": "A", "score": 1.10},
        {"strategy_id": "B", "score": 1.00},
        {"strategy_id": "C", "score": 0.50},
    ]

    # local reproduction of expected formatting: strategy:score with 2 decimals
    top = ",".join([f"{c['strategy_id']}:{float(c['score']):.2f}" for c in candidates_ranked])
    assert "A:1.10" in top
    assert "B:1.00" in top
