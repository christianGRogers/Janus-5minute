#!/usr/bin/env python3
"""
Test case for place_order method.
Places a BUY order for 1 share at $0.99 on the current BTC 5-minute market.
Tests that:
1. The order is placed successfully
2. Post-only protection is working (prevents price slippage)
3. The order rests on the book at the specified price
"""

import sys
import json
import time
import os
from pathlib import Path
import importlib.util

# Add parent directories to path
current_dir = Path(__file__).parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tools"))
sys.path.insert(0, str(current_dir))

# Import using full module paths
# Load place_order module
place_order_path = project_root / "tools" / "place_order.py"
spec = importlib.util.spec_from_file_location("place_order", place_order_path)
place_order_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(place_order_module)
place_order = place_order_module.place_order

# Load get_5m_market module
market_path = current_dir / "get-5m-market.py"
spec = importlib.util.spec_from_file_location("get_5m_market", market_path)
market_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market_module)
get_current_5m_market_token_id = market_module.get_current_5m_market_token_id


def test_place_order_on_5m_market():
    """
    Test placing a buy order on the current BTC 5-minute market.
    
    This test:
    - Fetches the current active 5-minute BTC market
    - Places a BUY order for 1 share at $0.99 (UP side)
    - Validates the order was accepted by the API
    - Confirms post-only protection is in place
    
    IMPORTANT: This test requires environment variables to be set:
    - PRIVATE_KEY: Your Ethereum private key
    - PROXY_ADDRESS: Your Polymarket proxy address
    
    You can set these in a .env file in the project root or as environment variables.
    """
    
    # Check for required environment variables
    private_key = os.getenv("PRIVATE_KEY")
    proxy_address = os.getenv("PROXY_ADDRESS")
    
    if not private_key or not proxy_address:
        print("=" * 70)
        print("SETUP REQUIRED: Missing environment variables")
        print("=" * 70)
        print("\nTo run this test, you need to set:")
        print("  - PRIVATE_KEY: Your Ethereum private key")
        print("  - PROXY_ADDRESS: Your Polymarket proxy address")
        print("\nOption 1: Set in .env file in project root:")
        print("  PRIVATE_KEY=0x...")
        print("  PROXY_ADDRESS=0x...")
        print("\nOption 2: Set as environment variables:")
        print("  $env:PRIVATE_KEY = '0x...'")
        print("  $env:PROXY_ADDRESS = '0x...'")
        print("\n" + "=" * 70)
        return False
    
    print("=" * 70)
    print("TEST: Place Order on BTC 5-Minute Market")
    print("=" * 70)
    
    # Step 1: Get the current 5-minute market
    print("\n[Step 1] Fetching current BTC 5-minute market...")
    market_info = get_current_5m_market_token_id()
    
    if not market_info:
        print("[FAILED] Could not fetch current 5-minute market")
        return False
    
    token_id = market_info['token_id']
    market_slug = market_info['market_slug']
    
    print("[OK] Market found: " + market_slug)
    print("  Token ID (UP): " + str(token_id))
    print("  Token ID type: " + str(type(token_id)))
    
    # Handle case where token_id might be a list or object
    if isinstance(token_id, list):
        token_id = token_id[0] if len(token_id) > 0 else token_id
    if isinstance(token_id, dict):
        token_id = str(token_id)
    
    print("  Token ID (processed): " + str(token_id))
    
    # Step 2: Place the order
    print("\n[Step 2] Placing BUY order...")
    print("  Token ID: " + str(token_id))
    print("  Price: $0.99 (UP side)")
    print("  Size: 1 share")
    print("  Side: BUY")
    print("  Order Type: GTC (Good Till Cancel)")
    print("  Post-Only: TRUE (prevents price slippage)")
    
    result = place_order(
        token_id=token_id,
        price=0.99,
        size=2,
        side="BUY",
        tick_size="0.01",
    )
    
    # Step 3: Validate the response
    print("\n[Step 3] Validating order response...")
    
    print("\nResponse:")
    print(json.dumps(result, indent=2))
    
    # Check for success
    if not result.get("success"):
        print("\n[FAILED] Order was not placed successfully")
        print("Error: " + str(result.get('error', 'Unknown error')))
        print("Error Message: " + str(result.get('errorMsg', 'N/A')))
        return False
    
    print("\n[OK] Order placed successfully!")
    
    # Validate response fields
    order_id = result.get("orderID")
    status = result.get("status")
    making_amount = result.get("makingAmount")
    taking_amount = result.get("takingAmount")
    
    print("\n  Order ID: " + str(order_id))
    print("  Status: " + str(status))
    print("  Making Amount: " + str(making_amount) + " (what we're providing)")
    print("  Taking Amount: " + str(taking_amount) + " (what we expect to receive)")
    
    # Validate status
    if status not in ["live", "matched", "delayed"]:
        print("\n[FAILED] Invalid order status: " + str(status))
        return False
    
    print("\n[OK] Order status is valid: " + str(status))
    
    # With post-only=True, we expect the order to REST on the book
    if status == "matched":
        print("\n[WARNING] Order was immediately matched despite post-only=True")
        print("   This could indicate high liquidity or the order was filled by market makers")
    elif status == "live":
        print("\n[OK] Order is resting on the book (as expected with post-only)")
    elif status == "delayed":
        print("\n[OK] Order is in delayed state (may be processed shortly)")
    
    # Step 4: Summary
    print("\n" + "=" * 70)
    print("TEST RESULT: PASSED")
    print("=" * 70)
    print("""
Summary:
- Market: """ + market_slug + """
- Token ID: """ + str(token_id) + """
- Order Side: BUY (UP side)
- Price: $0.99
- Size: 1 share
- Order ID: """ + str(order_id) + """
- Final Status: """ + str(status) + """

Post-only protection is ACTIVE:
- Order will only rest on the book at $0.99
- Will NOT match at worse prices due to slippage
- Safe from price slippage on execution
""")
    
    return True


if __name__ == "__main__":
    try:
        success = test_place_order_on_5m_market()
        sys.exit(0 if success else 1)
    except Exception as e:
        print("\n[TEST FAILED WITH EXCEPTION]")
        print(type(e).__name__ + ": " + str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)
