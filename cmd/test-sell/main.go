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
	fmt.Println("Placing a SELL order for 1 share of YES at $0.90")
	fmt.Println()

	// Sell 1 share at $0.90
	// NOTE: To sell, you must first own the shares. Since we don't have any shares yet,
	// we'll place a SELL order at a high price to test order placement.
	orderSize := 1.0
	price := 0.90

	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("Test: SELL 1 Share of YES @ $%.2f\n", price)
	fmt.Println(strings.Repeat("=", 70))
	orderID, err := engine.PlaceOrder(marketID, "SELL", price, orderSize)
	if err == nil && orderID != "" {
		fmt.Printf("✅ Test passed - Order placed successfully\n")
		fmt.Printf("   Order ID: %s\n", orderID)
		testsPassed++
	} else {
		fmt.Printf("❌ Test failed - Error: %v\n", err)
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
	fmt.Println("⚠️  This is a REAL order placed on the Polymarket production API")
	fmt.Println("    Selling 1 share of YES at $0.90")
	fmt.Println()

	if testsFailed > 0 {
		fmt.Printf("❌ %d test(s) failed\n", testsFailed)
		os.Exit(1)
	} else {
		fmt.Printf("✅ All %d tests passed!\n", testsPassed)
		os.Exit(0)
	}
}
