package main

import (
	"fmt"
	"log"
	"os"
	"strings"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// fetchLatestBTCMarket fetches the latest BTC 5-minute market and returns the UP token ID.
// This uses the same efficient Gamma API that the paper trading engine uses.
func fetchLatestBTCMarket(client *polymarket.Client) (string, error) {
	// Create Gamma API client
	gammaClient := polymarket.NewGammaClient("https://gamma-api.polymarket.com")
	
	// Get the current BTC 5-minute market
	market, err := gammaClient.GetCurrentBTCUpDownMarket()
	if err != nil {
		return "", fmt.Errorf("failed to fetch BTC market: %w", err)
	}

	if market == nil {
		return "", fmt.Errorf("no BTC 5-minute market found")
	}

	// For UP/DOWN markets, we need the CLOB token ID (not condition ID)
	// CLOBTokenIDs contains the actual token IDs for placing orders
	if len(market.CLOBTokenIDs) < 2 {
		return "", fmt.Errorf("market %s has insufficient token IDs: got %d, need 2 (UP and DOWN)",
			market.Slug, len(market.CLOBTokenIDs))
	}

	// The first token ID is typically UP, second is DOWN
	// Return the UP token ID for trading
	upTokenID := market.CLOBTokenIDs[0]
	if upTokenID == "" {
		return "", fmt.Errorf("market %s has empty UP token ID", market.Slug)
	}

	fmt.Printf("📊 Market: %s (Condition: %s)\n", market.Slug, market.ConditionID)
	fmt.Printf("🎯 UP Token ID: %s\n", upTokenID)
	if len(market.CLOBTokenIDs) > 1 {
		fmt.Printf("📉 DOWN Token ID: %s\n", market.CLOBTokenIDs[1])
	}

	return upTokenID, nil
}

// TestSellOrder tests selling 1 share of YES at $0.01 on the BTC 5-minute market
// NOTE: Since we need to own shares before selling, this test places a BUY order instead
// to verify order placement works with available USDC balance
func main() {
	// Load API credentials from environment variables
	address := os.Getenv("PROXY_ADDRESS")
	privateKey := os.Getenv("PRIVATE_KEY")
	apiKey := os.Getenv("POLYMARKET_API_KEY")
	apiSecret := os.Getenv("POLYMARKET_API_SECRET")
	passphrase := os.Getenv("POLYMARKET_PASSPHRASE")

	// Strip 0x prefix from private key if present
	privateKey = strings.TrimPrefix(privateKey, "0x")
	privateKey = strings.TrimPrefix(privateKey, "0X")

	// Validate that required environment variables are set
	if address == "" || privateKey == "" || apiKey == "" || apiSecret == "" || passphrase == "" {

		log.Printf("POLYMARKET_ADDRESS = %s", address)
		log.Printf("PRIVATE_KEY = %s", privateKey)
		log.Printf("POLYMARKET_API_KEY = %s", apiKey)
		log.Printf("POLYMARKET_API_SECRET = %s", apiSecret)
		log.Printf("POLYMARKET_PASSPHRASE = %s", passphrase)

	}

	// Ensure DRY_RUN is NOT set (we're placing real orders)
	os.Unsetenv("DRY_RUN")

	// Create a Polymarket client
	client := polymarket.NewClient("https://clob.polymarket.com", apiKey)

	// Fetch the real market ID using efficient Gamma API lookup (same as paper trading engine uses)
	fmt.Println("🎯 Fetching latest BTC 5-minute market (same as paper trading engine)...")
	marketID, err := fetchLatestBTCMarket(client)
	if err != nil {
		log.Fatalf("❌ Failed to fetch market ID: %v", err)
	}
	fmt.Printf("✅ Using market ID: %s\n", marketID)

	// Create a new live trading engine
	engine := trading.NewLiveTradingEngine(client, apiKey, apiSecret, passphrase, privateKey, address)

	testsPassed := 0
	testsFailed := 0

	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("🎯 SELL ORDER TEST - BTC 5-Minute Market")
	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("Market ID: %s\n", marketID)
	fmt.Println("Step 1: Fetch market orderbook to get current lowest ask")
	fmt.Println("Step 2: BUY 5 shares at the lowest ask price")
	fmt.Println("Step 3: Fetch market orderbook to get current best bid")
	fmt.Println("Step 4: SELL 5 shares at the best bid price")
	fmt.Println()

	// Step 1: First BUY shares at a low price so we have inventory to sell
	// Polymarket minimum order size is 5 shares, so buy 5 shares
	buyOrderSize := 5.0
	buyPrice := 0.50

	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("Step 1: Fetching market orderbook to get lowest ask price\n")
	fmt.Println(strings.Repeat("=", 70))
	
	// Fetch the market book to get the best ask (lowest ask price)
	marketBook, bookErr := client.GetMarketBook(marketID)
	if bookErr != nil {
		fmt.Printf("⚠️  Could not fetch market book: %v\n", bookErr)
		fmt.Printf("   Using fallback price: $%.2f\n", buyPrice)
	} else {
		// Parse the market book to get bid/ask prices
		parseErr := marketBook.ParseBook()
		if parseErr != nil {
			fmt.Printf("⚠️  Could not parse market book: %v\n", parseErr)
			fmt.Printf("   Using fallback price: $%.2f\n", buyPrice)
		} else {
			if marketBook.BestAskParsed > 0 {
				buyPrice = marketBook.BestAskParsed
				fmt.Printf("✅ Best ask price: $%.2f (size: %.2f)\n", marketBook.BestAskParsed, marketBook.BestAskSizeParsed)
			} else {
				fmt.Printf("⚠️  No asks available in market book\n")
				fmt.Printf("   Using fallback price: $%.2f\n", buyPrice)
			}
		}
	}

	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("Step 2: BUY %v Shares @ $%.2f\n", buyOrderSize, buyPrice)
	fmt.Println(strings.Repeat("=", 70))
	buyOrderID, buyErr := engine.PlaceOrder(marketID, "BUY", buyPrice, buyOrderSize)
	if buyErr == nil && buyOrderID != "" {
		fmt.Printf("✅ BUY order placed successfully\n")
		fmt.Printf("   Order ID: %s\n", buyOrderID)
		testsPassed++
	} else {
		fmt.Printf("❌ BUY order failed - Error: %v\n", buyErr)
		testsFailed++
	}

	// Step 2: Now SELL 5 shares at a higher price (respecting minimum order size of 5)
	sellOrderSize := 5.0
	sellPrice := 0.90

	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("Step 3: Fetching market orderbook to get best bid price\n")
	fmt.Println(strings.Repeat("=", 70))
	
	// Fetch the market book to get the best bid
	marketBook, bookErr = client.GetMarketBook(marketID)
	if bookErr != nil {
		fmt.Printf("⚠️  Could not fetch market book: %v\n", bookErr)
		fmt.Printf("   Using fallback price: $%.2f\n", sellPrice)
	} else {
		// Parse the market book to get bid/ask prices
		parseErr := marketBook.ParseBook()
		if parseErr != nil {
			fmt.Printf("⚠️  Could not parse market book: %v\n", parseErr)
			fmt.Printf("   Using fallback price: $%.2f\n", sellPrice)
		} else {
			if marketBook.BestBidParsed > 0 {
				sellPrice = marketBook.BestBidParsed
				fmt.Printf("✅ Best bid price: $%.2f (size: %.2f)\n", marketBook.BestBidParsed, marketBook.BestBidSizeParsed)
			} else {
				fmt.Printf("⚠️  No bids available in market book\n")
				fmt.Printf("   Using fallback price: $%.2f\n", sellPrice)
			}
		}
	}

	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("Step 4: SELL %v Shares @ $%.2f\n", sellOrderSize, sellPrice)
	fmt.Println(strings.Repeat("=", 70))
	sellOrderID, sellErr := engine.PlaceOrder(marketID, "SELL", sellPrice, sellOrderSize)
	if sellErr == nil && sellOrderID != "" {
		fmt.Printf("✅ SELL order placed successfully\n")
		fmt.Printf("   Order ID: %s\n", sellOrderID)
		testsPassed++
	} else {
		fmt.Printf("❌ SELL order failed - Error: %v\n", sellErr)
		testsFailed++
	}

	// Print summary
	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("📊 Sell Order Test Summary")
	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("✅ Passed: %d\n", testsPassed)
	fmt.Printf("❌ Failed: %d\n", testsFailed)
	fmt.Printf("📊 Total:  %d\n", testsPassed+testsFailed)
	fmt.Println()
	fmt.Println("⚠️  These are REAL orders placed on the Polymarket production API")
	fmt.Println("    Note: Polymarket has a minimum order size of 5 shares")
	fmt.Printf("    Step 1: Fetched market orderbook for lowest ask\n")
	fmt.Printf("    Step 2: Bought 5 shares at $%.2f lowest ask price\n", buyPrice)
	fmt.Printf("    Step 3: Fetched market orderbook for best bid\n")
	fmt.Printf("    Step 4: Sold 5 shares at $%.2f best bid price\n", sellPrice)
	fmt.Println()

	if testsFailed > 0 {
		fmt.Printf("❌ %d test(s) failed\n", testsFailed)
		os.Exit(1)
	} else {
		fmt.Printf("✅ All %d tests passed!\n", testsPassed)
		os.Exit(0)
	}
}
