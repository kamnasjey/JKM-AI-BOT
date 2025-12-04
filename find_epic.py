# find_epic.py
from ig_client import IGClient


def main():
    # Чи одоо LIVE key ашиглаж байгаа, тиймээс is_demo=False
    ig = IGClient.from_env(is_demo=False)

    # Эндээс хайх үгийг өөрчилж болно
    search_term = "Spot Gold ($1)"

    markets = ig.search_markets(search_term)

    print(f"Нийт олдсон market: {len(markets)}")
    for m in markets:
        epic = m.get("epic")
        name = m.get("instrumentName")
        mtype = m.get("instrumentType")
        expiry = m.get("expiry")
        print(f"EPIC: {epic} | Name: {name} | Type: {mtype} | Expiry: {expiry}")


if __name__ == "__main__":
    main()
