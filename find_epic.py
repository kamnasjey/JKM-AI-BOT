import sys
from ig_client import IGClient

# Зарим pair дээр (алтад) тусгай EPIC нэршил ашиглая
SPECIAL_EPICS = {
    "XAUUSD": [
        "CS.D.CFDGOLD.CFDGC.IP",
        "CS.D.CFDGOLD.BMU.IP",
        "CS.D.CFDGOLD.CFM.IP",
        "IX.D.SUNGOLD.CFD.IP",
        "IX.D.SUNGOLD.BMU.IP",
    ]
}

# Энгийн FX pair-үүд дээр туршиж үзэх EPIC pattern-ууд
FX_EPIC_PATTERNS = [
    "CS.D.FX{pair}.CFD.IP",
    "CS.D.FX{pair}.MINI.IP",
    "CS.D.{pair}.CFD.IP",
    "CS.D.{pair}.MINI.IP",
]


def main():
    if len(sys.argv) < 2:
        print("Хэрэглээ: python find_epic.py EURUSD")
        print("Жишээ:   python find_epic.py XAUUSD")
        sys.exit(1)

    pair = sys.argv[1].upper().replace("/", "")
    print(f"PAIR: {pair}")
    print("IGClient-ээр логин хийж байна...\n")

    ig = IGClient.from_env(is_demo=False)
    ig.login()  # Энэ чинь аль хэдийн амжилттай ажиллаж байгаа

    # 1) EPIC candidate-уудын жагсаалт бэлдэнэ
    if pair in SPECIAL_EPICS:
        epics = SPECIAL_EPICS[pair]
    else:
        # FX pattern-уудаас үүсгэнэ
        epics = []
        for pattern in FX_EPIC_PATTERNS:
            epics.append(pattern.format(pair=pair))

        # давхардлыг арилгана
        epics = list(dict.fromkeys(epics))

    print(f"{pair} дээр дараах EPIC candidate-уудыг шалгана:")
    for e in epics:
        print(f"  - {e}")

    print("\n=== TEST ЭХЭЛЛЭЭ ===\n")

    # 2) EPIC бүр дээр /prices ажиллуулж үзнэ
    for epic in epics:
        print(f"--- EPIC туршиж байна: {epic} ---")
        try:
            candles = ig.get_candles(epic, resolution="HOUR", max_points=10)
            n = len(candles) if candles is not None else 0
            print(f"  ✅ OK — candles амжилттай авлаа. Нийт: {n}")
        except Exception as e:
            print(f"  ❌ Алдаа: {e}")

        print()

    print("=== TEST ДУУСЛАА ===")
    print("✅ ✅ ✅ Амжилттай EPIC гарсан байвал дээрээс нь хараад тэрийгээ сонгоорой.")


if __name__ == "__main__":
    main()
