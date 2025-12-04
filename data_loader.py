# data_loader.py

import csv

def load_csv_candles(path: str, limit: int | None = None) -> list[dict]:
    """
    time,open,high,low,close баганатай CSV файлаас свечүүд уншина.
    Үр дүнд нь:
    [
      {"time": "2024-12-02 10:00", "open": 2600.0, "high": 2605.0, ...},
      ...
    ]
    гэсэн list буцаана.
    """
    candles: list[dict] = []

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candle = {
                "time": row["time"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
            candles.append(candle)

    if limit is not None:
        return candles[-limit:]

    return candles
