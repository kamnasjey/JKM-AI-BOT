# core/rr_filter.py

from risk import calc_rr


MIN_RR = 3.0  # Ганбаярын стандарт

def check_rr(entry: float, sl: float, logical_tps: list[float]) -> dict | None:
    """
    logical_tps = логик TP түвшнүүдийн жагсаалт (өмнөх high, S/R г.м).
    R:R ≥ 3 таарах TP олдвол тэрийг буцаана, олдохгүй бол None.
    """
    for tp in logical_tps:
        rr = calc_rr(entry, sl, tp)
        if rr is None:
            continue

        if rr >= MIN_RR:
            return {"tp": tp, "rr": rr}

    return None
