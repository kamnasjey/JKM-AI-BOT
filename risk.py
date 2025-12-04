# core/risk.py

def calc_rr(entry: float, sl: float, tp: float) -> float | None:
    """
    R:R тооцоолно.
    Жишээ: entry=2600, sl=2590, tp=2630
    risk = 10, reward = 30 → RR = 3.0 (1:3)
    """
    risk = abs(entry - sl)
    reward = abs(tp - entry)

    if risk == 0:
        return None

    return reward / risk
