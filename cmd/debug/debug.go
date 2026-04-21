package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type MarketInfo struct {
	ID            string   `json:"id"`
	Slug          string   `json:"slug"`
	Title         string   `json:"title"`
	Description   string   `json:"description"`
	Active        bool     `json:"active"`
	Closed        bool     `json:"closed"`
	ConditionID   string   `json:"conditionId"`
	CLOBTokenIDs  []string `json:"clob_token_ids"`
	CreatedAt     string   `json:"createdAt"`
	UpdatedAt     string   `json:"updatedAt"`
	VolumeUSDC    float64  `json:"volume_usd"`
	LiquidityUSDC float64  `json:"liquidity_usd"`
}

func main() {
	fmt.Println("Testing Gamma API connection...")
	fmt.Println()

	client := &http.Client{Timeout: 10 * time.Second}

	// Test: Query all major crypto 5-minute markets
	fmt.Println("=== Testing: Query specific 5-minute markets ===")
	
	cryptos := []string{"btc", "eth", "sol", "xrp", "bnb", "ada", "doge", "avax", "matic", "link"}

	// Calculate current 5-minute window timestamp
	now := time.Now().Unix()
	windowTS := now - (now % 300)

	foundCount := 0
	for _, crypto := range cryptos {
		slug := fmt.Sprintf("%s-updown-5m-%d", crypto, windowTS)
		endpoint := fmt.Sprintf("https://gamma-api.polymarket.com/markets?active=true&closed=false&slug=%s", slug)

		resp, err := client.Get(endpoint)
		if err != nil {
			fmt.Printf("❌ %s: ERROR: %v\n", crypto, err)
			continue
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(resp.Body)
		if err != nil {
			fmt.Printf("❌ %s: ERROR reading body: %v\n", crypto, err)
			continue
		}

		var markets []MarketInfo
		if err := json.Unmarshal(body, &markets); err != nil {
			fmt.Printf("❌ %s: ERROR decoding: %v\n", crypto, err)
			continue
		}

		if len(markets) > 0 {
			m := markets[0]
			foundCount++
			fmt.Printf("✓ %s: Found market\n", crypto)
			fmt.Printf("  Slug: %s\n", m.Slug)
			fmt.Printf("  ID: %s\n", m.ID)
			fmt.Printf("  Active: %v\n", m.Active)
			fmt.Printf("  Liquidity: $%.2f\n", m.LiquidityUSDC)
		} else {
			fmt.Printf("✗ %s: Market not found (may not be active)\n", crypto)
		}
	}

	fmt.Printf("\n=== Results ===\n")
	fmt.Printf("Found %d active 5-minute markets\n", foundCount)
}

func contains(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
