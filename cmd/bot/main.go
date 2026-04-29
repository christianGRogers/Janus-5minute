package main

import (
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"janus-bot/config"
	"janus-bot/pkg/analytics"
	"janus-bot/pkg/market"
	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/strategies"
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
	var tradingEngine trading.TradingEngine

	if cfg.PaperTradingEnabled {
		log.Println("Paper trading mode enabled")
		log.Println("📊 Paper Trading Realism Features:")
		log.Printf("  • Slippage modeling: %v\n", cfg.PaperTradingRealistic.EnableSlippage)
		log.Printf("  • Latency simulation: %v\n", cfg.PaperTradingRealistic.EnableLatency)
		log.Printf("  • Price staleness: %v\n", cfg.PaperTradingRealistic.EnablePriceStaleness)
		
		// Create realistic config from app config
		realisticCfg := &trading.RealisticExecutionConfig{
			EnableSlippage:        cfg.PaperTradingRealistic.EnableSlippage,
			SlippageFactorPercent: cfg.PaperTradingRealistic.SlippageFactorPercent,
			EnableLatency:         cfg.PaperTradingRealistic.EnableLatency,
			EnablePriceStaleness:  cfg.PaperTradingRealistic.EnablePriceStaleness,
			MaxPriceStalenessBps:  cfg.PaperTradingRealistic.MaxPriceStalenessBps,
		}
		tradingEngine = trading.NewPaperTradingEngineWithConfig(20, realisticCfg) // Start with 20 USDC
	} else {
		log.Println("Live trading mode enabled")
		log.Println("🚀 Connecting to Polymarket live API...")
		
		// Create live trading engine
		// Balance will be fetched from the API
		tradingEngine = trading.NewLiveTradingEngine(
			client,
			cfg.ApiKey,
			cfg.Passphrase,
			cfg.PrivateKey,
			cfg.Address,
		)
		log.Printf("✅ Live trading engine initialized for address: %s\n", cfg.Address)
	}

	// Create and initialize strategy
	var strategy strategies.Strategy
	strategy = strategies.NewLateEntryStrategy(tradingEngine)
	log.Printf("✅ Strategy loaded: %s\n", strategy.Name())

	// Create market logger for analytics
	marketLogger, err := analytics.NewMarketLogger(".")
	if err != nil {
		log.Printf("⚠️  Warning: Failed to initialize market logger: %v\n", err)
	} else {
		log.Printf("📊 Market logs will be saved to: %s\n", marketLogger.GetLogDirectory())
		defer marketLogger.Close()
	}

	// Set market close handler to resolve positions when markets transition
	fetcher.SetMarketCloseHandler(func(removedMarkets []string, finalPrices map[string]*polymarket.MarketBook) {
		if tradingEngine != nil {
			log.Printf("\n📍 Market Window Ended - Closing %d markets:\n", len(removedMarkets))
			totalPnL := 0.0
			for _, marketID := range removedMarkets {
				// Determine which outcome won based on final prices
				// At resolution: winning outcome ≈ 0.99 ($1), losing outcome ≈ 0.01 ($0)
				upKey := marketID + "-UP"
				downKey := marketID + "-DOWN"
				
				var upFinalPrice float64 = 0.50  // Default fallback
				var downFinalPrice float64 = 0.50 // Default fallback
				
				if upBook, exists := finalPrices[upKey]; exists && upBook != nil {
					upFinalPrice = upBook.BestBidParsed
				}
				if downBook, exists := finalPrices[downKey]; exists && downBook != nil {
					downFinalPrice = downBook.BestBidParsed
				}
				
				// Close UP positions at appropriate price
				upClosedPositions := tradingEngine.CloseMarketPositionsByOutcome(marketID, "UP", upFinalPrice)
				for _, pos := range upClosedPositions {
					status := "📈"
					if pos.NetProfitLoss < 0 {
						status = "📉"
					}
					fmt.Printf("%s Market %s (%s): Entry %.2f → Exit %.2f | Gross: $%.2f | Fees: $%.2f | Net P&L: $%.2f (%.1f%%)\n",
						status, pos.MarketID, pos.Outcome, pos.EntryPrice, pos.ExitPrice, pos.ProfitLoss, pos.EntryFee+pos.ExitFee, pos.NetProfitLoss, pos.ProfitPct)
					totalPnL += pos.NetProfitLoss
				}
				
				// Close DOWN positions at appropriate price
				downClosedPositions := tradingEngine.CloseMarketPositionsByOutcome(marketID, "DOWN", downFinalPrice)
				for _, pos := range downClosedPositions {
					status := "📈"
					if pos.NetProfitLoss < 0 {
						status = "📉"
					}
					fmt.Printf("%s Market %s (%s): Entry %.2f → Exit %.2f | Gross: $%.2f | Fees: $%.2f | Net P&L: $%.2f (%.1f%%)\n",
						status, pos.MarketID, pos.Outcome, pos.EntryPrice, pos.ExitPrice, pos.ProfitLoss, pos.EntryFee+pos.ExitFee, pos.NetProfitLoss, pos.ProfitPct)
					totalPnL += pos.NetProfitLoss
				}

				// Log market closure to analytics
				allClosedPositions := append(upClosedPositions, downClosedPositions...)
				if marketLogger != nil && len(allClosedPositions) > 0 {
					if err := marketLogger.LogMarketClosure(
						marketID,
						allClosedPositions,
						finalPrices,
						tradingEngine.GetBalance(),
						tradingEngine.GetCumulativeProfit(),
					); err != nil {
						log.Printf("⚠️  Failed to log market closure: %v\n", err)
					}
				}
			}
			if totalPnL != 0 {
				fmt.Printf("\n💰 Total Window P&L (after fees): $%.2f\n", totalPnL)
			}
			// Notify strategy of window change
			if strategy != nil {
				strategy.OnMarketWindowChange()
			}
		}
	})

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

			// Run strategy evaluation if enabled
			if strategy != nil && len(books) > 0 {
				signal := strategy.EvaluateV2(books)
				if signal.ShouldTrade {
					// Place order with metadata for slippage calculation and outcome type
					orderID, err := tradingEngine.PlaceOrderWithOutcome(signal.MarketID, signal.Side, signal.Price, signal.Size, signal.AvailableLiquidity, signal.Outcome)
					if err != nil {
						log.Printf("❌ Strategy order failed: %v", err)
					} else {
						log.Printf("✅ %s Strategy placed %s order: %s @ %.2f x %.0f shares (%s)", strategy.Name(), signal.Side, orderID, signal.Price, signal.Size, signal.Outcome)
					}
				}
			}

			// Show paper trading
			if tradingEngine != nil {
				fmt.Printf("\nPaper Trading Account:\n")
				fmt.Printf("  Balance: %.2f USDC\n", tradingEngine.GetBalance())
				fmt.Printf("  Profit: %.2f USDC\n", tradingEngine.GetCumulativeProfit())
				positions := tradingEngine.GetPositions()
				if len(positions) == 0 {
					fmt.Printf("  Positions: None\n")
				} else {
					fmt.Printf("  Positions:\n")
					for marketID, pos := range positions {
						fmt.Printf("    %s (%s): %s %.2f @ %.4f\n", marketID, pos.Direction, pos.Side, pos.Size, pos.AvgPrice)
					}
				}
			}
		}
	}
}
