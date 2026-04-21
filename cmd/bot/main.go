package main

import (
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"janus-bot/config"
	"janus-bot/pkg/market"
	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

func main() {
	// Load configuration
	cfg := config.DefaultConfig()

	// For local development, override with environment variables if available
	if apiKey := os.Getenv("POLYMARKET_API_KEY"); apiKey != "" {
		cfg.ApiKey = apiKey
	}
	if privateKey := os.Getenv("POLYMARKET_PRIVATE_KEY"); privateKey != "" {
		cfg.PrivateKey = privateKey
	}

	// Create Polymarket client
	client := polymarket.NewClient(cfg.ClibAPIEndpoint, cfg.ApiKey)

	// Create market data fetcher
	fetcher := market.NewMarketFetcher(client, cfg)
	fetcher.SetErrorHandler(func(err error) {
		log.Printf("ERROR: %v", err)
	})

	// Create trading engine
	var tradingEngine interface{}

	if cfg.PaperTradingEnabled {
		log.Println("Paper trading mode enabled")
		tradingEngine = trading.NewPaperTradingEngine(10000.0) // Start with 10,000 USDC
	} else {
		log.Println("Live trading mode enabled")
		// TODO: Create live trading engine with real order placement
		// tradingEngine = trading.NewLiveTrading(client, cfg)
	}

	// Start fetching market data
	fetcher.Start()
	log.Println("Market data fetcher started")
	log.Println("Discovering 5-minute crypto markets...")
	log.Println("Bot running continuously (Ctrl+C to stop)...")

	// Setup signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	// Run continuously with periodic market data display
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	discoveryReported := false

	for {
		select {
		case <-sigChan:
			// Graceful shutdown on CTRL+C or SIGTERM
			log.Println("\n📍 Shutdown signal received, cleaning up...")
			fetcher.Stop()
			log.Println("Market data fetcher stopped")
			log.Println("Bot shut down successfully")
			return

		case <-ticker.C:
			// Report discovered markets on first iteration
			if !discoveryReported {
				discoveredMarkets := fetcher.GetDiscoveredMarkets()
				if len(discoveredMarkets) > 0 {
					fmt.Printf("\n✓ Discovered %d 5-minute markets:\n", len(discoveredMarkets))
					for _, slug := range discoveredMarkets {
						fmt.Printf("  - %s\n", slug)
					}
					discoveryReported = true
				}
			}

			// Print current market data
			books := fetcher.GetAllLatestBooks()
			if len(books) > 0 {
				fmt.Printf("\n=== Market Data at %s ===\n", time.Now().Format("15:04:05"))

				for cacheKey, book := range books {
					if book != nil {
						fmt.Printf("Market: %s\n", cacheKey)
						fmt.Printf("  Best Bid: %.2f (size: %.2f)\n", book.BestBidParsed, book.BestBidSizeParsed)
						fmt.Printf("  Best Ask: %.2f (size: %.2f)\n", book.BestAskParsed, book.BestAskSizeParsed)
						fmt.Printf("  Total Liquidity: %.2f USDC\n", book.LiquidityParsed)
						fmt.Printf("  Spread: %.2f%%\n", ((book.BestAskParsed - book.BestBidParsed) / ((book.BestAskParsed + book.BestBidParsed) / 2)) * 100)
					}
				}
			}

			// Show paper trading
			if pt, ok := tradingEngine.(*trading.PaperTradingEngine); ok {
				fmt.Printf("\nPaper Trading Account:\n")
				fmt.Printf("  Balance: %.2f USDC\n", pt.GetBalance())
				positions := pt.GetPositions()
				if len(positions) == 0 {
					fmt.Printf("  Positions: None\n")
				} else {
					fmt.Printf("  Positions:\n")
					for marketID, pos := range positions {
						fmt.Printf("    %s: %s %.2f @ %.4f\n", marketID, pos.Side, pos.Size, pos.AvgPrice)
					}
				}
			}
		}
	}
}
