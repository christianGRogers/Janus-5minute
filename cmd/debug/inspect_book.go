package main

import (
	"fmt"
	"io"
	"net/http"
	"time"
)

func main() {
	fmt.Println("Inspecting CLOB API /book response...")
	fmt.Println()

	client := &http.Client{Timeout: 10 * time.Second}

	// Use a token ID from the debug output
	tokenID := "78679188905520181229228202193924678114908427820991659350255761176172115276730"
	endpoint := fmt.Sprintf("https://clob.polymarket.com/book?token_id=%s", tokenID)

	fmt.Printf("URL: %s\n\n", endpoint)

	resp, err := client.Get(endpoint)
	if err != nil {
		fmt.Printf("ERROR: %v\n", err)
		return
	}
	defer resp.Body.Close()

	fmt.Printf("Status: %d\n\n", resp.StatusCode)

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		fmt.Printf("ERROR reading body: %v\n", err)
		return
	}

	fmt.Println("Raw response:")
	fmt.Println(string(body))
}
