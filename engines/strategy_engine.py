# engines/strategy_engine.py

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Callable, Optional


# -----------------------------
# 1) IG-ээс ирсэн candidate trade-ийн стандарт загвар
# -----------------------------

@dataclass
class CandidateTrade:
    symbol: str               # EURUSD, XAUUSD гэх мэт
    direction: str            # "BUY" эсвэл "SELL"
    rr: float                 # reward:risk харьцаа (RR)
    timeframe: str            # "M15", "H1", "H4" ...
    entry: float
    sl: float
    tp: float

    # Дараа нь Fibo, structure, trend гэх мэт feature-үүдийг нэмж болно
    extra: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        base = asdict(self)
        # extra-г гол түвшинд нийлүүлээд field шиг харагдуулъя
        extra = base.pop("extra") or {}
        base.update(extra)
        return base


# -----------------------------
# 2) Strategy / Arga baril-ийн config загвар
# -----------------------------

@dataclass
class StrategyConfig:
    name: str                       # "RR 2+ only", "Trend Fibo Strategy" гэх мэт
    is_enabled: bool                # асаалттай/үгүй
    symbols: Optional[List[str]]    # ямар symbol дээр ажиллах вэ (None = бүгд)
    timeframes: Optional[List[str]] # ямар timeframe дээр ажиллах вэ (None = бүгд)
    min_rr: Optional[float] = None  # RR доод хязгаар
    direction: Optional[str] = None # зөвхөн BUY, зөвхөн SELL, эсвэл None = аль алинд
    rules: Optional[List[Dict[str, Any]]] = None
    """
    rules = [
      {"field": "rr", "op": ">=", "value": 2.0},
      {"field": "structure_ok", "op": "==", "value": True},
      {"field": "trend", "op": "==", "value": "UP"},
      ...
    ]
    """


# -----------------------------
# 3) Харьцуулах функц (>=, <=, ==, !=, in, not in ...)
# -----------------------------

def _compare(left: Any, op: str, right: Any) -> bool:
    """Нэг нөхцөлийг шалгана: left (op) right"""

    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right
    if op == "in":
        return left in right
    if op == "not in":
        return left not in right

    # үл мэдэгдэх оператор байвал шалгалт унана
    return False


def _match_rules(candidate_dict: Dict[str, Any], rules: List[Dict[str, Any]]) -> bool:
    """
    rules-д бичигдсэн бүх нөхцөлийг candidate хангаж байвал True.
    """
    if not rules:
        # rules байхгүй бол "OK" гэж үзэж болно
        return True

    for rule in rules:
        field = rule.get("field")
        op = rule.get("op")
        value = rule.get("value")

        # тухайн field candidate дээр байхгүй бол унана
        if field not in candidate_dict:
            return False

        if not _compare(candidate_dict[field], op, value):
            return False

    return True


# -----------------------------
# 4) Нэг стратеги дээр candidate-ийг шалгах
# -----------------------------

def apply_strategy_to_candidate(
    candidate: CandidateTrade,
    strategy: StrategyConfig
) -> bool:
    """
    Энэ candidate тухайн strategy-ийн нөхцөлийг хангаж байна уу? (тийм/үгүй)
    """

    if not strategy.is_enabled:
        return False

    data = candidate.to_dict()

    # Symbol filter
    if strategy.symbols is not None and candidate.symbol not in strategy.symbols:
        return False

    # Timeframe filter
    if strategy.timeframes is not None and candidate.timeframe not in strategy.timeframes:
        return False

    # Direction filter (BUY / SELL)
    if strategy.direction is not None and candidate.direction != strategy.direction:
        return False

    # Min RR filter
    if strategy.min_rr is not None and candidate.rr < strategy.min_rr:
        return False

    # Дэлгэрэнгүй rules (фича дээр суурилсан)
    if strategy.rules:
        if not _match_rules(data, strategy.rules):
            return False

    return True


# -----------------------------
# 5) Зах зээл дээрх бүх candidate-үүдэд бүх стратегиудыг гүйлгэх
# -----------------------------

def run_strategies(
    candidates: List[CandidateTrade],
    strategies: List[StrategyConfig],
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    candidates: IG-ээс авсан бүх боломжит trade-үүд
    strategies: тухайн user-ийн идэвхжүүлсэн арга барилууд
    user_id: хүсвэл user бүрийн ID-г дамжуулж болно (DB лог, owner гэх мэтэд)

    Буцаах бүтэц:
    [
      {
        "user_id": "...",
        "strategy_name": "...",
        "symbol": "EURUSD",
        "direction": "BUY",
        "rr": 2.5,
        "timeframe": "H1",
        "entry": ...,
        "sl": ...,
        "tp": ...,
        "source": "IG",        # хаанаас ирсэн data гэдгийг тэмдэглэж болно
      },
      ...
    ]
    """

    results = []

    for candidate in candidates:
        for strategy in strategies:
            if apply_strategy_to_candidate(candidate, strategy):
                results.append({
                    "user_id": user_id,
                    "strategy_name": strategy.name,
                    "symbol": candidate.symbol,
                    "direction": candidate.direction,
                    "rr": candidate.rr,
                    "timeframe": candidate.timeframe,
                    "entry": candidate.entry,
                    "sl": candidate.sl,
                    "tp": candidate.tp,
                    "source": "IG",
                })

    return results


# -----------------------------
# 6) ЖИШЭЭ – яг яаж ашиглахыг харуулъя
# -----------------------------

if __name__ == "__main__":
    # 1) IG-ээс авсан data-г ийм хэлбэрт хөрвүүлсэн гэж төсөөлье
    c1 = CandidateTrade(
        symbol="EURUSD",
        direction="BUY",
        rr=2.3,
        timeframe="H1",
        entry=1.0850,
        sl=1.0800,
        tp=1.0950,
        extra={"structure_ok": True, "trend": "UP"},
    )

    c2 = CandidateTrade(
        symbol="XAUUSD",
        direction="SELL",
        rr=1.5,
        timeframe="M15",
        entry=2600,
        sl=2610,
        tp=2580,
        extra={"structure_ok": False, "trend": "DOWN"},
    )

    candidates = [c1, c2]

    # 2) USER-ийн арга барилуудын config жишээ

    rr_only = StrategyConfig(
        name="RR 2+ only",
        is_enabled=True,
        symbols=None,                  # бүх symbol
        timeframes=None,               # бүх timeframe
        min_rr=2.0,
        direction=None,                # BUY, SELL аль аль нь байж болно
        rules=None,                    # нэмэлт rule алга
    )

    trend_and_structure = StrategyConfig(
        name="Trend Fibo Style",
        is_enabled=True,
        symbols=["EURUSD", "GBPUSD"],  # зөвхөн эдгээр дээр
        timeframes=["H1", "H4"],
        min_rr=2.0,
        direction="BUY",
        rules=[
            {"field": "structure_ok", "op": "==", "value": True},
            {"field": "trend", "op": "==", "value": "UP"},
        ],
    )

    strategies = [rr_only, trend_and_structure]

    # 3) engine-г ажиллуулъя
    signals = run_strategies(candidates, strategies, user_id="user_123")

    from pprint import pprint
    pprint(signals)
