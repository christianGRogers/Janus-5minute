#!/usr/bin/env python3
"""
Get Polymarket account USDC balance using py-clob-client-v2.
This script is called by the Go LiveTradingEngine to fetch real balance from Polymarket.
"""

import os
import sys
import json
from dotenv import load_dotenv

try:
    from py_clob_client_v2 import ClobClient
    from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
except ImportError as e:
    print(json.dumps({
        "balance": 0,
        "status": "error",
        "message": f"Failed to import py_clob_client_v2: {e}"
    }))
    sys.exit(1)

# Load environment variables
load_dotenv()


def get_balance():
    """Fetch and return USDC balance, or print error and exit with status 1"""
    try:
        # Initialize client
        host = 'https://clob.polymarket.com'
        chain_id = 137  # Polygon mainnet
        
        # Get credentials from environment
        private_key = os.getenv("PRIVATE_KEY")
        address = os.getenv("POLYMARKET_ADDRESS")
        if not address:
            address = os.getenv("PROXY_ADDRESS")
        
        if not address or not private_key:
            raise ValueError("Missing required environment variables: POLYMARKET_ADDRESS or PROXY_ADDRESS or PRIVATE_KEY")
        
        # Strip 0x prefix if present
        if private_key.startswith("0x"):
            private_key = private_key[2:]
        
        # Create temp client WITHOUT credentials first (for deriving API key)
        # CRITICAL: Must use signature_type=3 (POLY_1271) with the proxy address (funder)
        # This ensures the API key is bound to the proxy address for V2 deposit wallets
        temp_client = ClobClient(
            host=host,
            key=private_key,
            chain_id=chain_id,
            signature_type=3,  # POLY_1271 (EIP-1271) - for V2 deposit wallet proxy
            funder=address
        )
        
        # Derive API credentials using L1 → L2 auth flow
        # CRITICAL: The API key MUST be derived with the exact same signature_type and funder
        # as will be used in the trading client. Otherwise the API key will be bound to a
        # different address and orders will be rejected.
        try:
            api_creds = temp_client.create_or_derive_api_key()
            print(f"DEBUG: API credentials derived successfully", file=sys.stderr)
        except Exception as e:
            print(f"DEBUG: Failed to derive API credentials: {e}", file=sys.stderr)
            raise
        
        # Create authenticated client with derived credentials
        # CRITICAL: Must use the SAME signature_type=3 as the temp_client
        client = ClobClient(
            host=host,
            key=private_key,
            chain_id=chain_id,
            signature_type=3,  # POLY_1271 (EIP-1271) - MUST match temp_client
            funder=address,
            creds=api_creds
        )
        
        # Get balance allowance - this includes available collateral
        try:
            from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
            balance_response = client.get_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            # Balance is in smallest units (6 decimals for USDC), convert to USD
            balance_usdc = int(balance_response.get("balance", 0)) / 10**6
            print(f"DEBUG: Balance retrieved: ${balance_usdc}", file=sys.stderr)
        except Exception as e:
            print(f"DEBUG: Failed to get balance: {e}", file=sys.stderr)
            raise
        
        if balance_usdc > 0:
            # Output in JSON format for easy parsing by Go
            print(json.dumps({"balance": balance_usdc, "status": "success"}))
            return 0
        else:
            print(json.dumps({"balance": 0, "status": "error", "message": "Balance is zero or not accessible"}))
            return 1
            
    except Exception as e:
        print(json.dumps({"balance": 0, "status": "error", "message": str(e)}))
        return 1


if __name__ == '__main__':
    sys.exit(get_balance())
