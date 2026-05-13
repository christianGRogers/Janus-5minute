# Polymarket Order Test

A self-contained test script that places a $1 order on Polymarket, following the official Python quickstart guide. You can either let it auto-select an active market or specify a market by name.

## Prerequisites

- Python 3.7+
- `py-clob-client-v2` SDK

Install dependencies:
```bash
pip install py-clob-client-v2 requests
```

## Setup

Before running the test, you must set your environment variables with valid credentials:

```powershell
# On Windows PowerShell
$env:PRIVATE_KEY="your_private_key_hex_string"
$env:DEPOSIT_WALLET_ADDRESS="your_deposit_wallet_address"
```

**Note:** 
- The private key should be your wallet's hex-encoded private key (e.g., `0x...`)
- The deposit wallet address should be your funded Polymarket trading wallet

## Running the Test

### Auto-select an active market:
```bash
python order_test.py
```

### Specify a market by slug (from Polymarket URL):
```bash
# From https://polymarket.com/event/fed-decision-in-october
python order_test.py "fed-decision-in-october"

# Or use environment variable
$env:MARKET_SLUG="fed-decision-in-october"
python order_test.py
```

### Specify a market by name or keyword:
```bash
# Command line argument
python order_test.py "Bitcoin"

# Or use environment variable
$env:MARKET_NAME="Bitcoin"
python order_test.py
```

The market search is **case-insensitive** and looks for partial matches in market questions.

## Finding Market Slugs and IDs

### From Polymarket Website
The slug is visible in the URL:
```
https://polymarket.com/event/fed-decision-in-october
                                 ↑
                        Slug: fed-decision-in-october
```

### Using Gamma API
To browse available markets, you can query the Gamma API directly:
```bash
# Get highest volume active markets
curl "https://gamma-api.polymarket.com/events?active=true&closed=false&order=volume_24hr&limit=10"

# Search by tag
curl "https://gamma-api.polymarket.com/events?tag_id=100381&limit=10&active=true&closed=false"

# Get markets for a specific event slug
curl "https://gamma-api.polymarket.com/markets?slug=fed-decision-in-october"
```

## What the Test Does

1. **Derives API credentials** from your private key using the Polymarket SDK
2. **Initializes the trading client** with `POLY_1271` signature type (recommended for new users with deposit wallets)
3. **Fetches markets** using the Gamma API (`https://gamma-api.polymarket.com`)
   - Queries for active, non-closed markets ordered by 24hr volume
   - Searches by slug first, then searches by name in market questions
4. **Places a $1 BUY order** at mid-price (0.50) on a market token
5. **Checks order status** and displays your open orders and trade history

## How Market Lookup Works

The script uses the **Gamma API** for efficient market discovery:

### Market Selection Priority:
1. **If you specify a market:** Try slug lookup first, then search by name in active markets
2. **If you don't specify:** Auto-select the first active market with volume

### Market Filters:
- `active=true` (market is live)
- `closed=false` (market hasn't resolved)
- `order=volume_24hr` (sorted by recent activity)

### Gamma API Endpoints Used:
- `GET /events?active=true&closed=false&order=volume_24hr` - Fetch active events
- `GET /markets?slug={slug}` - Fetch specific market by slug

## Output Example

```
============================================================
Polymarket Order Test
============================================================

[1/5] Deriving API credentials...
✓ API credentials derived
[2/5] Initializing trading client...
✓ Trading client initialized
[3/5] Fetching available markets...
✓ Found 150 markets
  Using market: Will Bitcoin reach $100k by end of 2026?
  Token ID: 12345678
  Tick size: 0.01
[4/5] Placing $1 order...
  Price: $0.5
  Size: 2.0 tokens
  Total cost: $1.0
✓ Order placed successfully
  Order ID: abc123def456
  Status: PENDING
[5/5] Checking orders...
✓ You have 1 open orders
✓ You've made 1 trades

============================================================
Test completed successfully!
============================================================
```

## Documentation Reference

Based on the Polymarket Python Quickstart Guide:
- Full documentation: https://docs.polymarket.com/llms.txt
- Client initialization and API key derivation
- Order placement with `create_and_post_order()`
- Order checking with `get_orders()` and `get_trades()`

## Troubleshooting

**L2 AUTH NOT AVAILABLE - Invalid Signature**
- Check that your `PRIVATE_KEY` and `DEPOSIT_WALLET_ADDRESS` are correct
- For new users, use signature type `POLY_1271`

**Order rejected - insufficient balance**
- Ensure your deposit wallet has pUSD tokens
- Make sure you have more pUSD than what's committed in open orders

**Order rejected - insufficient allowance**
- Your deposit wallet needs approval for the Exchange contract
- See the Deposit Wallet Guide in the Polymarket docs

## Next Steps

- Modify `price` and `size` parameters to place different orders
- Implement order cancellation using `client.cancel(order_id=...)`
- Explore different market types and multi-outcome markets
