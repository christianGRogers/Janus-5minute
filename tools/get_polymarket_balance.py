#!/usr/bin/env python3
"""
Get Polymarket account USDC balance using py-clob-client.
This script is called by the Go LiveTradingEngine to fetch real balance from Polymarket.
"""

import os
import sys
import json
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

# Load environment variables
load_dotenv()


def get_usdc_balance_ext(self, *args, **kwargs) -> float:
    """Get USDC balance in USD (converted from smallest unit)"""
    params = BalanceAllowanceParams(signature_type=1, asset_type=AssetType.COLLATERAL)
    d = self.get_balance_allowance(params=params)
    return int(d["balance"]) / 10**6


def get_balance():
    """Fetch and return USDC balance, or print error and exit with status 1"""
    try:
        # Add method to ClobClient class
        ClobClient.get_usdc_balance = get_usdc_balance_ext
        
        # Initialize client
        host = 'https://clob.polymarket.com'
        
        # Use Amoy testnet (80002) if DRY_RUN is enabled, otherwise use Polygon mainnet (POLYGON = 137)
        if os.getenv("DRY_RUN") == "true":
            chain_id = 80002  # Amoy testnet
        else:
            chain_id = POLYGON  # Polygon mainnet (137)
        
        address = os.getenv("POLYMARKET_ADDRESS")
        key = os.getenv("PRIVATE_KEY")
        
        if not address or not key:
            raise ValueError("Missing required environment variables: POLYMARKET_ADDRESS or PRIVATE_KEY")
        
        signature_type = 1  # Email/Magic wallet signatures
        client = ClobClient(host=host, key=key, chain_id=chain_id, signature_type=signature_type, funder=address)
        credentials = client.create_or_derive_api_creds()
        client.set_api_creds(credentials)
        
        # Get balance
        cash = client.get_usdc_balance()
        
        if cash > 0:
            # Output in JSON format for easy parsing by Go
            print(json.dumps({"balance": cash, "status": "success"}))
            return 0
        else:
            print(json.dumps({"balance": 0, "status": "error", "message": "Balance is zero or not accessible"}))
            return 1
            
    except Exception as e:
        print(json.dumps({"balance": 0, "status": "error", "message": str(e)}))
        return 1


if __name__ == '__main__':
    sys.exit(get_balance())
