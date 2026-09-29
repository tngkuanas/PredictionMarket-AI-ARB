import sys
from src.api.polymarket import PolymarketClient
from src.db.duckdb_store import get_db

def test_live_polymarket():
    client = PolymarketClient()
    print("Connecting to Polymarket Gamma API...")
    markets = client.fetch_active_markets(limit=10)
    print(f"Successfully fetched {len(markets)} active markets!")
    for m in markets[:5]:
        print(f"Market ID: {m.market_id} | Title: {m.title}")
        print(f"  Category: {m.category} | Volume: ${m.volume:,.0f} | Liquidity: ${m.liquidity:,.0f}")
        print(f"  Tokens: {m.clob_token_ids}")

    if markets:
        sample = markets[0]
        if sample.clob_token_ids:
            token_id = sample.clob_token_ids[0]
            print(f"\nFetching live orderbook for token {token_id}...")
            ob = client.fetch_order_book(token_id)
            print(f"  Orderbook bids: {len(ob.get('bids', []))}, asks: {len(ob.get('asks', []))}")
            if ob.get("bids"):
                print(f"  Top bid: {ob['bids'][0]}")
            if ob.get("asks"):
                print(f"  Top ask: {ob['asks'][0]}")

            print(f"\nFetching price history for token {token_id}...")
            history = client.fetch_price_history(token_id, interval="1m", fidelity_minutes=60)
            print(f"  Price history points returned: {len(history)}")
            if history:
                print(f"  Latest price snapshot: {history[-1].timestamp} -> mid: {history[-1].yes_mid}")

        db = get_db()
        db.save_markets(markets)
        saved = db.get_all_markets()
        print(f"\nDuckDB verified: {len(saved)} markets in database table.")

if __name__ == "__main__":
    test_live_polymarket()
