package main

import (
	"fmt"
	"log"
	"os"
	"strings"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// TestPlaceOrderDryRun demonstrates the dry-run mode for safe order placement testing
// without sending real orders to the Polymarket API
func main() {
	// Load API credentials from environment variables
	address := os.Getenv("POLYMARKET_ADDRESS")
	privateKey := os.Getenv("PRIVATE_KEY")
	apiKey := os.Getenv("POLYMARKET_API_KEY")
	passphrase := os.Getenv("POLYMARKET_PASSPHRASE")

	// Strip 0x prefix from private key if present
	privateKey = strings.TrimPrefix(privateKey, "0x")
	privateKey = strings.TrimPrefix(privateKey, "0X")

	// Validate that required environment variables are set
	if address == "" || privateKey == "" || apiKey == "" || passphrase == "" {
		log.Fatal("❌ Error: Missing required environment variables. Please set:")
		fmt.Println("  - POLYMARKET_ADDRESS")
		fmt.Println("  - PRIVATE_KEY")
		fmt.Println("  - POLYMARKET_API_KEY")
		fmt.Println("  - POLYMARKET_PASSPHRASE")
		return
	}

	// Enable dry-run mode for safe testing
	os.Setenv("DRY_RUN", "true")

	// Create a Polymarket client
	client := polymarket.NewClient("https://clob.polymarket.com", apiKey)

	// Create a new live trading engine with DRY_RUN enabled
	engine := trading.NewLiveTradingEngine(client, apiKey, passphrase, privateKey, address)

	testsPassed := 0
	testsFailed := 0

	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("🏜️  DRY-RUN MODE - Testing Order Placement With Verbose API Logging")
	fmt.Println(strings.Repeat("=", 70))
	fmt.Println("Orders WILL be sent to the actual Polymarket API")
	fmt.Println("Requests and responses will be logged for review and debugging")
	fmt.Println()

	// Test 1: PlaceOrder - Basic BUY order
	fmt.Println(strings.Repeat("=", 70))
	fmt.Println("Test 1: PlaceOrder - Basic BUY Order")
	fmt.Println(strings.Repeat("=", 70))
	orderID1, err1 := engine.PlaceOrder(
		"test-market-1",
		"BUY",
		0.55,  // Price: 55 cents
		10,    // Size: 10 USDC
	)
	if err1 == nil && orderID1 != "" {
		fmt.Printf("✅ Test passed - Order sent to API successfully\n")
		fmt.Printf("   Order ID: %s\n", orderID1)
		testsPassed++
	} else {
		fmt.Printf("❌ Test failed - Error sending order\n")
		fmt.Printf("   Got: %s, Error: %v\n", orderID1, err1)
		testsFailed++
	}

	// Test 2: PlaceOrder - SELL order
	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("Test 2: PlaceOrder - SELL Order")
	fmt.Println(strings.Repeat("=", 70))
	orderID2, err2 := engine.PlaceOrder(
		"test-market-2",
		"SELL",
		0.45,  // Price: 45 cents
		5,     // Size: 5 USDC
	)
	if err2 == nil && orderID2 != "" {
		fmt.Printf("✅ Test passed - Order sent to API successfully\n")
		fmt.Printf("   Order ID: %s\n", orderID2)
		testsPassed++
	} else {
		fmt.Printf("❌ Test failed - Error sending order\n")
		fmt.Printf("   Got: %s, Error: %v\n", orderID2, err2)
		testsFailed++
	}

	// Test 3: PlaceOrderWithOutcome - BUY with UP outcome
	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("Test 3: PlaceOrderWithOutcome - BUY with UP Outcome")
	fmt.Println(strings.Repeat("=", 70))
	orderID3, err3 := engine.PlaceOrderWithOutcome(
		"test-market-3",
		"BUY",
		0.60,   // Price: 60 cents
		15,     // Size: 15 USDC
		1000,   // Available liquidity: 1000 USDC
		"UP",   // Outcome type
	)
	if err3 == nil && orderID3 != "" {
		fmt.Printf("✅ Test passed - Order sent to API successfully\n")
		fmt.Printf("   Order ID: %s\n", orderID3)
		testsPassed++
	} else {
		fmt.Printf("❌ Test failed - Error sending order\n")
		fmt.Printf("   Got: %s, Error: %v\n", orderID3, err3)
		testsFailed++
	}

	// Test 4: PlaceOrderWithOutcome - SELL with DOWN outcome
	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("Test 4: PlaceOrderWithOutcome - SELL with DOWN Outcome")
	fmt.Println(strings.Repeat("=", 70))
	orderID4, err4 := engine.PlaceOrderWithOutcome(
		"test-market-4",
		"SELL",
		0.40,    // Price: 40 cents
		8,       // Size: 8 USDC
		1000,    // Available liquidity: 1000 USDC
		"DOWN",  // Outcome type
	)
	if err4 == nil && orderID4 != "" {
		fmt.Printf("✅ Test passed - Order sent to API successfully\n")
		fmt.Printf("   Order ID: %s\n", orderID4)
		testsPassed++
	} else {
		fmt.Printf("❌ Test failed - Error sending order\n")
		fmt.Printf("   Got: %s, Error: %v\n", orderID4, err4)
		testsFailed++
	}

	// Test 5: Invalid price (should fail local validation)
	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("Test 5: PlaceOrder - Invalid Price (should fail locally)")
	fmt.Println(strings.Repeat("=", 70))
	_, err5 := engine.PlaceOrder(
		"test-market-5",
		"BUY",
		1.50,  // Invalid: price > 1
		1,
	)
	if err5 != nil {
		fmt.Printf("✅ Test passed - Correctly rejected invalid price\n")
		fmt.Printf("   Error: %v\n", err5)
		testsPassed++
	} else {
		fmt.Printf("❌ Test failed - Should have rejected invalid price\n")
		testsFailed++
	}

	// Test 6: Invalid size (should fail local validation)
	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("Test 6: PlaceOrder - Invalid Size (should fail locally)")
	fmt.Println(strings.Repeat("=", 70))
	_, err6 := engine.PlaceOrder(
		"test-market-6",
		"BUY",
		0.50,
		-1,  // Invalid: negative size
	)
	if err6 != nil {
		fmt.Printf("✅ Test passed - Correctly rejected invalid size\n")
		fmt.Printf("   Error: %v\n", err6)
		testsPassed++
	} else {
		fmt.Printf("❌ Test failed - Should have rejected invalid size\n")
		testsFailed++
	}

	// Print summary
	fmt.Println("\n" + strings.Repeat("=", 70))
	fmt.Println("🏜️  Dry-Run Test Summary")
	fmt.Println(strings.Repeat("=", 70))
	fmt.Printf("✅ Passed: %d\n", testsPassed)
	fmt.Printf("❌ Failed: %d\n", testsFailed)
	fmt.Printf("📊 Total:  %d\n", testsPassed+testsFailed)
	fmt.Println()
	fmt.Println("ℹ️  All 'passed' orders were sent to the actual Polymarket API.")
	fmt.Println("    Review the verbose logging above to see request/response details.")
	fmt.Println()

	// Exit with appropriate code
	if testsFailed > 0 {
		fmt.Printf("❌ %d test(s) failed\n", testsFailed)
		os.Exit(1)
	} else {
		fmt.Printf("✅ All %d tests passed!\n", testsPassed)
		os.Exit(0)
	}
}
