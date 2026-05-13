"""
Self-contained order test for Polymarket.

This script demonstrates placing a $1 order on Polymarket,
following the Polymarket Python quickstart guide:
https://docs.polymarket.com/llms.txt

You can specify a market by:
1. Slug (from URL): python order_test.py "fed-decision-in-october"
2. Name/keyword: python order_test.py "Bitcoin"
"""

import os
import sys
import requests
from py_clob_client_v2 import ClobClient, SignatureTypeV2, OrderArgs, OrderType
from py_clob_client_v2.order_builder.constants import BUY


GAMMA_API = "https://gamma-api.polymarket.com"




def main():
    """Place a $1 order on a specified or first available market."""
    
    # Check for market name/slug argument or environment variable
    market_query = "Bitcoin"
    
    # Step 1: Set Up Your Client
    print("=" * 60)
    print("Polymarket Order Test")
    print("=" * 60)
    
    host = "https://clob.polymarket.com"
    chain = 137  # Polygon mainnet
    private_key = os.getenv("PRIVATE_KEY")
    deposit_wallet_address = os.getenv("DEPOSIT_WALLET_ADDRESS")
    if not private_key or not deposit_wallet_address:
        print("ERROR: Missing environment variables")
        print("Required: PRIVATE_KEY, DEPOSIT_WALLET_ADDRESS")
        print("\nUsage: python order_test.py [market_name_or_slug]")
        print("Examples:")
        print('  python order_test.py "Bitcoin"')
        print('  python order_test.py "fed-decision-in-october"')
        return
    
    print("\n[1/5] Deriving API credentials...")
    # Derive API credentials
    temp_client = ClobClient(host, key=private_key, chain_id=chain)
    api_creds = temp_client.create_or_derive_api_key()
    print("[OK] API credentials derived")
    
    # Initialize trading client
    print("[2/5] Initializing trading client...")
    client = ClobClient(
        host,
        key=private_key,
        chain_id=chain,
        creds=api_creds,
        signature_type=SignatureTypeV2.POLY_1271,
        funder=deposit_wallet_address
    )
    print("[OK] Trading client initialized")
    
    # Step 2: Fetch markets and find the one we want
    print("[3/5] Fetching markets...")

    response = requests.get(
    "https://gamma-api.polymarket.com/markets/slug/hantavirus-pandemic-in-2026",
    # params={"active": "true", "closed": "false", "limit": 1}
    )
    market = response.json()

    print(market["question"])
    print(market["clobTokenIds"])

    
    print(f"  Using market: {market.get('question', 'Unknown')}")
    
    # Extract token ID
    token_ids = market["clobTokenIds"]
    import json

    parsed = json.loads(token_ids)

    token_id = parsed[1] # Choose the second token ID (e.g. "No" side) for this market
    print(f"  Extracted token ID: {token_id}")
    token_id = None


    tick_size = market.get("tick_size", "0.01")
    
    print(f"  Token ID: {token_id}")
    print(f"  Tick size: {tick_size}")
    
    # Step 3: Calculate order size based on $1
    print("[4/5] Placing $1 order...")
    price = 0.50  # Mid-price estimate
    size = 1.0 / price  # Size to spend $1
    
    print(f"  Price: ${price}")
    print(f"  Size: {size} tokens")
    print(f"  Total cost: ${size * price}")
    
    # Step 4: Create and post order
    try:
        from py_clob_client_v2 import PartialCreateOrderOptions
        
        response = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=0.932,
                size=5,
                side=BUY,
            ),
            options=PartialCreateOrderOptions(
                tick_size=tick_size,
                neg_risk=False,
            ),
            order_type=OrderType.GTC
        )
        
        print(f"[OK] Order placed successfully")
        print(f"  Order ID: {response['orderID']}")
        print(f"  Status: {response['status']}")
        
    except Exception as e:
        print(f"ERROR: Failed to place order")
        print(f"  {str(e)}")
        print(f"\n  Note: This market may not have an active orderbook yet.")
        print(f"  Try with a different market or check if the market is still active.")
        return
    
    # Step 5: Check order status
    print("[5/5] Checking orders...")
    try:
        open_orders = client.get_orders()
        print(f"[OK] You have {len(open_orders)} open orders")
        
        # Print recent trades
        trades = client.get_trades()
        print(f"[OK] You've made {len(trades)} trades")
        
    except Exception as e:
        print(f"WARNING: Could not fetch orders/trades: {str(e)}")
    
    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
