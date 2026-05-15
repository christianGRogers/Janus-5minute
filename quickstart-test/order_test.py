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
from py_clob_client_v2.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client_v2.constants import POLYGON

GAMMA_API = "https://gamma-api.polymarket.com"




def main():
    """Place a $1 order on a specified or first available market."""
    
    host = "https://clob.polymarket.com"
    private_key = os.getenv("PRIVATE_KEY")
    proxy_address = os.getenv("PROXY_ADDRESS") 
    chain = 137  # Polygon mainnet
    
    print("[1/5] Deriving API credentials with correct signature type...")
    
    # Create temp client with the SAME configuration as the trading client
    # This ensures the API credentials are derived for the correct signer/funder combination
    temp_client = ClobClient(
        host=host,
        key=private_key,
        chain_id=chain,
        signature_type=2,           # ← POLY_1271 (EIP-1271) - MUST match trading client
        funder=proxy_address,       # MUST match trading client
    )
    
    try:
        # CRITICAL: The API key MUST be derived with the exact same signature_type and funder
        # as will be used in the trading client. Otherwise the API key will be bound to a
        # different address and orders will be rejected with "order signer address has to be the address of the API KEY"
        api_creds = temp_client.create_or_derive_api_key()
        print(f"[OK] API credentials derived successfully")
        print(f"     API key: {api_creds.api_key[:20]}...")
    except Exception as e:
        print(f"ERROR: Failed to derive API credentials: {e}")
        print(f"       Make sure the proxy address is correct and deployed on-chain")
        return
    
    # Create trading client with derived credentials
    print("[2/5] Initializing trading client...")
    client = ClobClient(
        host=host,
        key=private_key,
        chain_id=chain,
        creds=api_creds,
        signature_type=3,           # ← POLY_1271 (EIP-1271) - MUST match temp_client
        funder=proxy_address,       # MUST match temp_client
    )
    print("[OK] Trading client initialized")
    
    # Verify configuration before placing orders
    print("[2b/5] Verifying wallet configuration...")
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider("https://polygon-rpc.com"))
        code = w3.eth.get_code(proxy_address)
        if len(code) == 0:
            print(f"ERROR: Proxy address {proxy_address} has no bytecode on-chain")
            print(f"       The proxy must be deployed first. Try depositing funds via Polymarket UI.")
            return
        print(f"[OK] Proxy is deployed on-chain ({len(code)} bytes)")
    except Exception as e:
        print(f"WARNING: Could not verify proxy on-chain: {e}")
    
    # Check balance and allowances
    print("[2c/5] Checking balance and allowances...")
    try:
        balance_data = client.get_balance_allowance(
            params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        balance = float(balance_data.get("balance", "0"))
        print(f"[OK] Balance: ${balance}")
        
        if balance == 0:
            print(f"ERROR: Balance is 0. Your wallet has no funds deposited.")
            print(f"       Deposit funds via Polymarket UI first.")
            return
        
        allowances = balance_data.get("allowances", {})
        print(f"[OK] Allowances verified: {len(allowances)} contracts approved")
    except Exception as e:
        print(f"ERROR: Could not fetch balance/allowances: {e}")
        print(f"       This usually means the API key is bound to the wrong address.")
        print(f"       Re-derive the API key by running this script again.")
        return
    
    # Step 3: Fetch markets and find the one we want
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
                price=0.90,
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
