package main

import (
	"fmt"
	"log"
	"os"
	"strings"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

func main() {
	// Load API credentials from environment variables (matching Python script)
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
	// CLOB API only needs address and privateKey for authentication
	// apiKey, apiSecret and passphrase are not used for balance-allowance endpoint
	engine := trading.NewLiveTradingEngine(client, "", "", "", privateKey, address)

	// Fetch and display balance
	balance := engine.GetBalance()

	if balance > 0 {
		fmt.Printf("💰 Cash Balance: $%.2f USD\n", balance)
	} else {
		fmt.Println("❌ Error: Failed to retrieve cash balance")
		os.Exit(1)
	}
}
