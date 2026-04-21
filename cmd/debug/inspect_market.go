package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

func main() {
	fmt.Println("Inspecting BTC market response from Gamma API...")
	fmt.Println()

	client := &http.Client{Timeout: 10 * time.Second}

	// Calculate current 5-minute window timestamp
	now := time.Now().Unix()
	windowTS := now - (now % 300)
	slug := fmt.Sprintf("btc-updown-5m-%d", windowTS)

	endpoint := fmt.Sprintf("https://gamma-api.polymarket.com/markets?active=true&closed=false&slug=%s", slug)

	resp, err := client.Get(endpoint)
	if err != nil {
		fmt.Printf("ERROR: %v\n", err)
		return
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		fmt.Printf("ERROR reading body: %v\n", err)
		return
	}

	// Print raw JSON
	fmt.Println("Raw JSON response:")
	fmt.Println(string(body))
	fmt.Println()

	// Try to parse and pretty print
	var data interface{}
	if err := json.Unmarshal(body, &data); err != nil {
		fmt.Printf("ERROR decoding JSON: %v\n", err)
		return
	}

	prettyJSON, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		fmt.Printf("ERROR formatting JSON: %v\n", err)
		return
	}

	fmt.Println("Pretty printed:")
	fmt.Println(string(prettyJSON))
}
