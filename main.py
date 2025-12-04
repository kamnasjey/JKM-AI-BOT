from ai_explainer import explain_signal_ganbayar
from ig_client import IGClient
from strategy import analyze_xauusd_full


def main():
    pair = "XAUUSD"

    # LIVE API key ашиглаад явж байгаа, өмнөх шиг is_demo=False
    ig = IGClient.from_env(is_demo=False)

    # Чиний IG дээрх Spot Gold ($1)-ийн EPIC
    epic_xauusd = "CS.D.CFDGOLD.BMU.IP"

    # ---------- IG-ээс олон timeframe-ийн свеч татах ----------
    d1_candles = ig.get_candles(epic_xauusd, resolution="DAY", max_points=200)
    h4_candles = ig.get_candles(epic_xauusd, resolution="HOUR_4", max_points=200)
    h1_candles = ig.get_candles(epic_xauusd, resolution="HOUR", max_points=200)
    m15_candles = ig.get_candles(epic_xauusd, resolution="MINUTE_15", max_points=200)

    decision = analyze_xauusd_full(d1_candles, h4_candles, h1_candles, m15_candles)
    status = decision.get("status")

    fib_zone = decision.get("fib_zone")

    print("===== ГАНБАЯР MULTI-TF IG ANALYZER (v2) =====")
    print(f"PAIR: {pair}")
    print("D1:")
    print(f"  Trend : {decision.get('d1_trend')}")
    print(f"  Levels: {decision.get('d1_levels')}")
    print("H4:")
    print(f"  Trend : {decision.get('h4_trend')}")
    print(f"  Levels: {decision.get('h4_levels')}")
    if fib_zone:
        print(f"  Fib 0.5–0.618 zone: {fib_zone}")
    print()

    if status == "no_data":
        print("❌ Өгөгдөл дутуу:", decision.get("reason"))
        print("============================================")
        return

    if status == "no_trade":
        print("ℹ NO TRADE:", decision.get("reason"))
        print("============================================")
        return

    if status == "no_trade_rr":
        print("Direction:", decision.get("direction"))
        print("Entry    :", decision.get("entry"))
        print("SL       :", decision.get("sl"))
        print("TP candidates:", decision.get("tp_candidates"))
        print()
        print("❌ R:R ≥ 1:3 хангах TP олдсонгүй. NO TRADE.")
        print("============================================")
        return

    if status == "trade":
        direction = decision["direction"]
        entry = decision["entry"]
        sl = decision["sl"]
        tp = decision["tp"]
        rr = decision["rr"]
        tp_candidates = decision.get("tp_candidates")

        print("ENTRY TF: M15")
        print(f"Direction: {direction}")
        print(f"Entry    : {entry}")
        print(f"SL       : {sl}")
        print(f"TP candidates: {tp_candidates}")
        print()
        print(f"✅ Сонгосон TP: {tp} | R:R ≈ 1:{rr:.2f}")
        print("   Ганбаярын стандартын дагуу боломжит", direction, "сетап.")
        print()

        signal = {
            "pair": pair,
            "direction": direction,
            "timeframe": decision.get("entry_tf", "M15"),
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "rr": rr,
            "context": {
                "d1_trend": decision.get("d1_trend"),
                "d1_levels": decision.get("d1_levels"),
                "h4_trend": decision.get("h4_trend"),
                "h4_levels": decision.get("h4_levels"),
                "fib_zone": fib_zone,
            },
        }

        try:
            explanation = explain_signal_ganbayar(signal)
            print("----- ГАНБАЯРЫН АРГА БАРИЛААРХ ТАЙЛБАР (GPT) -----")
            print(explanation)
            print("-------------------------------------------------")
        except Exception as e:
            print("⚠ AI тайлбар авах үед алдаа гарлаа:", e)

        print("============================================")
        return

    print("⚠ Тодорхойгүй статус:", status)
    print(decision)
    print("============================================")


if __name__ == "__main__":
    main()
