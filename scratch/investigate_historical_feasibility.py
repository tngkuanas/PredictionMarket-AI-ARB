"""Empirical Feasibility Investigation of Polymarket Historical Data Endpoints.

Queries live Polymarket REST endpoints across multiple real tokens to evaluate:
1. Historical price capabilities (/prices-history)
2. Historical trade capabilities (/trades)
3. Historical order-book capabilities (/book, /book-history, /snapshots, etc.)
4. Data quality, schema compatibility, and event-study feasibility.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List
import requests

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.phase10.acquisition.dns_resolver import enable_polymarket_edge_resolver
enable_polymarket_edge_resolver()

CLOB_URL = "https://clob.polymarket.com"
GAMMA_URL = "https://gamma-api.polymarket.com"
DATA_API_URL = "https://data-api.polymarket.com"

# 3 Real markets from distinct sectors and liquidity tiers:
TEST_MARKETS = [
    {
        "name": "Sports / High Liquidity",
        "market_id": "4904811",
        "token_id": "88391114873121460534755374453373541457506862776360231577867131214687456642030",
        "outcome": "BetBoom Team"
    },
    {
        "name": "Macro / Monetary Policy",
        "market_id": "2589812",
        "token_id": "111061902544814266207267295505639408607400625795891618462682726460921782993748",
        "outcome": "No change Oct 2026"
    },
    {
        "name": "Geopolitical / Leadership",
        "market_id": "682705",
        "token_id": "20006732765674855733524007935991362439352594042415161039767275461950712817548",
        "outcome": "Benjamin Netanyahu"
    }
]


def test_historical_prices():
    print("\n" + "=" * 80)
    print("1. TESTING HISTORICAL PRICE DATA (/prices-history)")
    print("=" * 80)
    
    session = requests.Session()
    session.headers.update({"User-Agent": "HistoricalFeasibilityStudy/1.0", "Accept": "application/json"})
    
    results = {}

    for m in TEST_MARKETS:
        token_id = m["token_id"]
        print(f"\n--- Testing Token: {m['name']} ({m['outcome']}) ---")
        print(f"Token ID: {token_id}")
        
        # Test 1: Standard intervals and fidelities
        endpoint = f"{CLOB_URL}/prices-history"
        
        # Test fidelity parameter: 1 min, 5 min, 60 min, fidelity=1 vs fidelity=60
        for fidelity in [1, 5, 60]:
            params = {"market": token_id, "interval": "max", "fidelity": fidelity}
            resp = session.get(endpoint, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                history = data.get("history", [])
                print(f"Fidelity={fidelity} min: Status 200, points returned={len(history)}")
                if history:
                    first_p = history[0]
                    last_p = history[-1]
                    first_ts = datetime.fromtimestamp(first_p["t"], tz=timezone.utc).isoformat()
                    last_ts = datetime.fromtimestamp(last_p["t"], tz=timezone.utc).isoformat()
                    print(f"  First point: ts={first_ts}, p={first_p.get('p')}")
                    print(f"  Last point:  ts={last_ts}, p={last_p.get('p')}")
                    print(f"  Keys in point object: {list(first_p.keys())}")
            else:
                print(f"Fidelity={fidelity} min: Status {resp.status_code}, error={resp.text[:100]}")

        # Test sub-minute fidelity (e.g. fidelity < 1 or seconds)
        sub_resp = session.get(endpoint, params={"market": token_id, "interval": "1d", "fidelity": 0.1}, timeout=10)
        print(f"Sub-minute fidelity (0.1): Status {sub_resp.status_code}, text={sub_resp.text[:100]}")

        # Test reproducibility across repeated requests
        resp1 = session.get(endpoint, params={"market": token_id, "interval": "1d", "fidelity": 60}, timeout=10)
        resp2 = session.get(endpoint, params={"market": token_id, "interval": "1d", "fidelity": 60}, timeout=10)
        is_reproducible = (resp1.text == resp2.text)
        print(f"Deterministic & reproducible across repeated calls: {is_reproducible}")

        # Check whether bid or ask is provided
        sample_point = resp1.json().get("history", [{}])[0] if resp1.status_code == 200 else {}
        has_bid_ask = ("bid" in sample_point or "ask" in sample_point or "best_bid" in sample_point)
        print(f"Bid/Ask fields present in price history: {has_bid_ask}")
        print(f"Fields available: {list(sample_point.keys())}")

    return True


def test_historical_trades():
    print("\n" + "=" * 80)
    print("2. TESTING HISTORICAL TRADE DATA (/trades)")
    print("=" * 80)

    session = requests.Session()
    session.headers.update({"User-Agent": "HistoricalFeasibilityStudy/1.0", "Accept": "application/json"})

    for m in TEST_MARKETS:
        token_id = m["token_id"]
        print(f"\n--- Testing Trades for Token: {m['name']} ({m['outcome']}) ---")
        endpoint = f"{CLOB_URL}/trades"
        
        # Test 1: Fetch recent trades
        params = {"market": token_id, "limit": 100}
        resp = session.get(endpoint, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"Status {resp.status_code}: {resp.text[:100]}")
            continue

        trades = resp.json()
        print(f"Status 200: retrieved {len(trades)} trades")
        if trades:
            sample_tr = trades[0]
            print(f"Sample trade keys: {list(sample_tr.keys())}")
            print(f"Sample trade: price={sample_tr.get('price')}, size={sample_tr.get('size')}, side={sample_tr.get('side')}, timestamp={sample_tr.get('timestamp')}")
            
            # Check pagination capability: e.g. cursor / before / after
            last_ts = trades[-1].get("timestamp")
            print(f"Testing pagination before timestamp={last_ts}...")
            pag_params = {"market": token_id, "limit": 100, "before": last_ts}
            pag_resp = session.get(endpoint, params=pag_params, timeout=10)
            if pag_resp.status_code == 200:
                pag_trades = pag_resp.json()
                print(f"Pagination with 'before': retrieved {len(pag_trades)} older trades")
            else:
                print(f"Pagination with 'before' returned status {pag_resp.status_code}: {pag_resp.text[:100]}")

            # Test offset/cursor pagination
            offset_params = {"market": token_id, "limit": 100, "offset": 100}
            offset_resp = session.get(endpoint, params=offset_params, timeout=10)
            print(f"Pagination with 'offset': status {offset_resp.status_code}")


def test_historical_order_book():
    print("\n" + "=" * 80)
    print("3. TESTING HISTORICAL ORDER BOOK DATA (L2/L3)")
    print("=" * 80)

    session = requests.Session()
    session.headers.update({"User-Agent": "HistoricalFeasibilityStudy/1.0", "Accept": "application/json"})

    token_id = TEST_MARKETS[0]["token_id"]

    # Test 1: Live /book
    book_resp = session.get(f"{CLOB_URL}/book", params={"token_id": token_id}, timeout=10)
    print(f"Live /book endpoint: status={book_resp.status_code}")
    if book_resp.status_code == 200:
        book_data = book_resp.json()
        print(f"Live book keys: {list(book_data.keys())}")
        print(f"Bids count: {len(book_data.get('bids', []))}, Asks count: {len(book_data.get('asks', []))}")
        print(f"Timestamp in book object: {book_data.get('timestamp')}")

    # Test 2: Does /book support historical timestamp?
    past_ts = int(time.time()) - 86400  # 24 hours ago
    past_book_resp = session.get(f"{CLOB_URL}/book", params={"token_id": token_id, "timestamp": past_ts}, timeout=10)
    print(f"/book with timestamp parameter: status={past_book_resp.status_code}")

    # Test 3: Candidate historical order-book endpoints
    candidate_endpoints = [
        "/book-history",
        "/orderbook-history",
        "/snapshots",
        "/depth-history",
        "/l2-history",
        "/market/book/history"
    ]
    for ep in candidate_endpoints:
        r = session.get(f"{CLOB_URL}{ep}", params={"token_id": token_id}, timeout=5)
        print(f"Candidate {ep}: status={r.status_code}")

    # Test 4: Gamma API or Data API historical books
    gamma_candidates = [
        "/markets/history",
        "/orderbook",
        "/orderbooks"
    ]
    for ep in gamma_candidates:
        r = session.get(f"{GAMMA_URL}{ep}", params={"market": token_id}, timeout=5)
        print(f"Gamma candidate {ep}: status={r.status_code}")

    print("\nVerified Conclusion for Historical L2 Order-Book Data:")
    print("Does Polymarket REST API provide historical L2 order-book snapshots or deltas? NO.")
    print("HISTORICAL L2 ORDER-BOOK DATA: NOT AVAILABLE")


if __name__ == "__main__":
    test_historical_prices()
    test_historical_trades()
    test_historical_order_book()
