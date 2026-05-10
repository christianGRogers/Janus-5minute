#!/usr/bin/env python3
"""
Fetches all active, open Polymarket markets and extracts the condition_id
for every market that has an UP outcome token.

Cache keys in the trading strategy are built as "{condition_id}-UP",
so condition_id is the market ID we care about.
"""

import requests

API_BASE_URL = "https://clob.polymarket.com"


def fetch_market_ids(base_url: str = API_BASE_URL) -> list[str]:
    """
    Fetch all active market IDs that have an UP outcome token.
    Follows pagination automatically via next_cursor.

    Args:
        base_url: Polymarket CLOB API base URL.

    Returns:
        List of unique condition_id strings.
    """
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    market_ids: list[str] = []
    seen: set[str] = set()
    cursor: str = ""

    while True:
        params: dict[str, str] = {"active": "true", "closed": "false"}
        if cursor:
            params["next_cursor"] = cursor

        response = session.get(f"{base_url}/markets", params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()

        for market in payload.get("data", []):
            condition_id = market.get("condition_id")
            if not condition_id:
                continue

            tokens = market.get("tokens", [])
            has_up = any(t.get("outcome", "").upper() == "UP" for t in tokens)

            if has_up and condition_id not in seen:
                seen.add(condition_id)
                market_ids.append(condition_id)

        # "LTE=" is Polymarket's sentinel value for the last page
        next_cursor = payload.get("next_cursor", "")
        if not next_cursor or next_cursor == "LTE=":
            break

        cursor = next_cursor

    return market_ids


if __name__ == "__main__":
    print("Fetching active Polymarket market IDs with UP outcomes...")
    ids = fetch_market_ids()
    print(f"Found {len(ids)} markets:\n")
    for market_id in ids:
        print(f"  {market_id}")
