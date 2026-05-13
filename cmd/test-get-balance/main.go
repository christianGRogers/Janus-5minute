package main

import (
	"fmt"
	"log"
	"os"
	"strings"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// TestGetBalance is an integration test that verifies the LiveTradingEngine.GetBalance()
// method works correctly by calling the Python balance script
func main() {
	// Load API credentials from environment variables
	address := os.Getenv("POLYMARKET_ADDRESS")
	privateKey := os.Getenv("PRIVATE_KEY")

	// Strip 0x prefix from private key if present
	privateKey = strings.TrimPrefix(privateKey, "0x")
	privateKey = strings.TrimPrefix(privateKey, "0X")

	// Validate that required environment variables are set
	if address == "" || privateKey == "" {
		log.Fatal("❌ Error: Missing required environment variables. Please set:")
		fmt.Println("  - POLYMARKET_ADDRESS")
		fmt.Println("  - PRIVATE_KEY")
		return
	}

	// Create a Polymarket client
	client := &polymarket.Client{}

	// Create a new live trading engine
	engine := trading.NewLiveTradingEngine(client, "", "", "", privateKey, address)

	// Test GetBalance interface
	fmt.Println("Testing LiveTradingEngine.GetBalance()...")
	balance := engine.GetBalance()

	if balance > 0 {
		fmt.Printf("✅ Test passed - 💰 Cash Balance: $%.2f USD\n", balance)
		os.Exit(0)
	} else {
		fmt.Println("❌ Test failed - Error: Failed to retrieve cash balance")
		os.Exit(1)
	}
}
