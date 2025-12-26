
import sys
import codecs
from ig_client import IGClient

# Force UTF-8 for Windows Console
if sys.stdout.encoding != 'utf-8':
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

# Candidates
SPECIAL_EPICS = {
    "XAUUSD": [
        "CS.D.CFDGOLD.CFDGC.IP", # Standard
        "CS.D.CFDGOLD.BMU.IP",   # Mini
        "CS.D.CFDGOLD.CFM.IP",   # ?
        "IX.D.SUNGOLD.CFD.IP",   # Index?
        "IX.D.SUNGOLD.BMU.IP",
        "CS.D.USCGC.TODAY.IP",   # GC Futures
        "CS.D.USCGC.CFD.IP",     # GC Spot CFD?
        "CS.D.CFDGOLD.IFM.IP"
    ]
}

FX_EPIC_PATTERNS = [
    "CS.D.FX{pair}.CFD.IP",
    "CS.D.FX{pair}.MINI.IP",
    "CS.D.{pair}.CFD.IP",
    "CS.D.{pair}.MINI.IP",
]

def main():
    if len(sys.argv) < 2:
        print("Usage: python find_epic.py EURUSD")
        return

    pair = sys.argv[1].upper().replace("/", "")
    print(f"PAIR: {pair}")
    print("Logging in...")

    ig = IGClient.from_env()

    if pair in SPECIAL_EPICS:
        epics = SPECIAL_EPICS[pair]
    else:
        epics = []
        for pattern in FX_EPIC_PATTERNS:
            epics.append(pattern.format(pair=pair))
        epics = list(dict.fromkeys(epics))

    print(f"Checking candidates for {pair}:")
    for e in epics:
        print(f"  - {e}")

    print("\n=== STARTING TEST ===\n")

    valid_found = []

    for epic in epics:
        print(f"Testing: {epic} ...", end=" ")
        try:
            # Try to fetch just 5 candles
            candles = ig.get_candles(epic, resolution="HOUR", max_points=5)
            n = len(candles) if candles is not None else 0
            print(f"[OK] Got {n} candles.")
            if n > 0:
                valid_found.append(epic)
        except Exception as e:
            print(f"[FAIL] {e}")

    print("\n=== TEST COMPLETED ===")
    if valid_found:
        print("VALID EPICS FOUND:")
        for e in valid_found:
            print(f" -> {e}")
    else:
        print("No valid EPIC found.")

if __name__ == "__main__":
    main()
