#!/usr/bin/env python3
"""
Place an order on Polymarket using the py-clob-client SDK.
This script handles proper EIP-712 signing and order placement.
"""

import os
import sys
import json
import argparse
import traceback
from dotenv import load_dotenv

try:
    from py_clob_client_v2 import ClobClient
    from py_clob_client_v2.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
    from py_clob_client_v2.order_builder.constants import BUY, SELL
except ImportError as e:
    print(json.dumps({
        "success": False,
        "error": f"Failed to import py_clob_client_v2: {e}",
        "errorMsg": f"Missing dependency: {e}"
    }))
    sys.exit(1)

# Load environment variables
load_dotenv()


def place_order(token_id, price, size, side, tick_size="0.01", neg_risk=False):
    """
    Place an order on Polymarket
    
    Args:
        token_id: The token ID for the market
        price: The price (0-1)
        size: The order size in USDC
        side: BUY or SELL
        tick_size: Minimum tick size for the market
        neg_risk: Whether this is a negative risk market
    
    Returns:
        Dict with order result or error
    """
    try:
        # Get credentials
        private_key = os.getenv("PRIVATE_KEY")
        address = os.getenv("PROXY_ADDRESS")  # The address that will fund the order (must match API key derivation)
        
        if not private_key or not address:
            return {
                "success": False,
                "error": "Missing PRIVATE_KEY or PROXY_ADDRESS environment variables"
            }
        
        # Strip 0x prefix if present
        if private_key.startswith("0x"):
            private_key = private_key[2:]
        
        print(f"DEBUG: Initializing ClobClient with address={address}, chain_id=137", file=sys.stderr)
        
        # Initialize CLOB client WITHOUT credentials first (for derivation)
        # Use Polygon mainnet (137) - CLOB is only on mainnet
        host = "https://clob.polymarket.com"
        chain_id = 137
        
        # Create temporary client to derive API credentials
        temp_client = ClobClient(
            host=host,
            key=private_key,
            chain_id=chain_id,
            signature_type=0,  # EOA signature
            funder=address
        )
        
        print(f"DEBUG: Deriving API credentials (L1 → L2 auth)", file=sys.stderr)
        
        # Derive API credentials using L1 → L2 auth flow
        try:
            api_creds = temp_client.create_or_derive_api_key()
            print(f"DEBUG: API credentials derived successfully", file=sys.stderr)
        except Exception as e:
            print(f"DEBUG: Failed to derive API credentials: {e}", file=sys.stderr)
            return {
                "success": False,
                "error": f"Failed to derive API credentials: {e}",
                "errorMsg": str(e)
            }
        
        # Initialize authenticated client with derived credentials
        client = ClobClient(
            host=host,
            key=private_key,
            chain_id=chain_id,
            signature_type=0,  # EOA signature
            funder=address,
            creds=api_creds
        )
        
        print(f"DEBUG: Client initialized, creating order: token_id={token_id}, price={price}, size={size}, side={side}", file=sys.stderr)
        
        # Fetch market details to get correct tick_size and neg_risk
        print(f"DEBUG: Fetching market details", file=sys.stderr)
        try:
            # Get market details using condition ID or token ID
            # For v2, we may need to fetch market info differently
            markets = client.get_markets()
            market_info = None
            
            # Find the market containing this token
            for market in markets:
                if market.get("tokens"):
                    for token in market["tokens"]:
                        if str(token.get("token_id", "")) == str(token_id):
                            market_info = market
                            break
                if market_info:
                    break
            
            if market_info:
                tick_size = str(market_info.get("minimum_tick_size", tick_size))
                neg_risk = market_info.get("neg_risk", neg_risk)
                print(f"DEBUG: Found market - tick_size={tick_size}, neg_risk={neg_risk}", file=sys.stderr)
            else:
                print(f"DEBUG: Market details not found, using defaults - tick_size={tick_size}, neg_risk={neg_risk}", file=sys.stderr)
        except Exception as e:
            print(f"DEBUG: Could not fetch market details: {e}, using defaults", file=sys.stderr)
        
        print(f"DEBUG: Calling create_and_post_order with order_type=GTC", file=sys.stderr)
        
        # Create and post order with order_type parameter (v2 API)
        response = client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=BUY if side.upper() == "BUY" else SELL
            ),
            options=PartialCreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
            order_type=OrderType.GTC  # Good Till Cancel
        )
        
        print(f"DEBUG: Order response: {response}", file=sys.stderr)
        
        return {
            "success": True,
            "orderID": response.get("orderID", ""),
            "status": response.get("status", ""),
            "makingAmount": response.get("makingAmount", ""),
            "takingAmount": response.get("takingAmount", ""),
            "errorMsg": ""
        }
        
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"ERROR: {error_trace}", file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "errorMsg": str(e),
            "traceback": error_trace
        }


def main():
    parser = argparse.ArgumentParser(description="Place an order on Polymarket")
    parser.add_argument("--token-id", required=True, help="Token ID")
    parser.add_argument("--price", type=float, required=True, help="Price (0-1)")
    parser.add_argument("--size", type=float, required=True, help="Order size")
    parser.add_argument("--side", required=True, choices=["BUY", "SELL"], help="Order side")
    parser.add_argument("--tick-size", default="0.01", help="Tick size (default: 0.01)")
    parser.add_argument("--neg-risk", action="store_true", help="Negative risk market")
    
    args = parser.parse_args()
    
    result = place_order(
        token_id=args.token_id,
        price=args.price,
        size=args.size,
        side=args.side,
        tick_size=args.tick_size,
        neg_risk=args.neg_risk
    )
    
    # Output JSON for Go to parse
    print(json.dumps(result))
    
    # Exit with appropriate code
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
