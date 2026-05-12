#!/usr/bin/env python3
"""
Fetches the current 5-minute BTC market token ID from Polymarket using the Gamma API.
"""

import requests
import time

GAMMA_API_BASE_URL = "https://gamma-api.polymarket.com"


def get_current_5m_market_token_id():
    """
    Fetches the current active 5-minute BTC market and returns its token ID.
    
    Uses the Gamma API to query for markets with the slug format: btc-updown-5m-{timestamp}
    where timestamp is the Unix timestamp of the 5-minute window start.
    
    Returns:
        dict: Contains 'token_id', 'condition_id', 'market_slug', and market details
    """
    
    # Get current time to determine which 5-minute market window we're in
    current_timestamp = int(time.time())
    
    # Calculate the start of the current 5-minute window
    # Each window is 300 seconds (5 minutes)
    window_start_timestamp = (current_timestamp // 300) * 300
    
    # Construct the market slug for the current 5-minute window
    # Format: "btc-updown-5m-{timestamp}"
    market_slug = f"btc-updown-5m-{window_start_timestamp}"
    
    print(f"Looking for market: {market_slug}")
    
    # Query the Gamma API for markets matching this slug
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    
    params = {
        "slug": market_slug,
        "active": "true",
        "closed": "false"
    }
    
    try:
        response = session.get(f"{GAMMA_API_BASE_URL}/markets", params=params, timeout=10)
        response.raise_for_status()
        markets = response.json()
        
        # The Gamma API returns an array directly
        if markets and len(markets) > 0:
            market = markets[0]
            
            # Extract the UP token ID from clobTokenIds
            clob_token_ids = market.get("clobTokenIds", [])
            
            if clob_token_ids and len(clob_token_ids) > 0:
                # First token is typically UP, second is DOWN
                up_token_id = clob_token_ids[0]
                
                result = {
                    "token_id": up_token_id,
                    "condition_id": market.get("conditionId"),
                    "market_slug": market.get("slug"),
                    "up_token": up_token_id,
                    "market_data": market
                }
                
                return result
        
        print("Market not found")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching market data: {e}")
        return None


if __name__ == "__main__":
    market_info = get_current_5m_market_token_id()
    
    if market_info:
        print("\n=== Current 5-Minute BTC Market ===")
        print(f"Token ID: {market_info['token_id']}")
        print(f"Condition ID: {market_info['condition_id']}")
        print(f"Market Slug: {market_info['market_slug']}")
    else:
        print("Could not find current 5-minute BTC market")
