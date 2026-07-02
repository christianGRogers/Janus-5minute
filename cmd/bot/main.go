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
	if address := os.Getenv("PROXY_ADDRESS"); address != "" {
		cfg.Address = address
	}
	if privateKey := os.Getenv("PRIVATE_KEY"); privateKey != "" {
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
		tradingEngine = trading.NewPaperTradingEngineWithConfig(15.80, realisticCfg) // Start with 20 USDC
	} else {
		log.Println("Live trading mode enabled")
		log.Println("🚀 Connecting to Polymarket live API...")
		
		// Create live trading engine
		// Balance will be fetched from the API
		tradingEngine = trading.NewLiveTradingEngine(
			client,
			cfg.ApiKey,
			cfg.ApiSecret,
			cfg.Passphrase,
			cfg.PrivateKey,
			cfg.Address,
		)
		log.Printf("✅ Live trading engine initialized for address: %s\n", cfg.Address)
	}

	// Create and initialize strategy
	var strategy strategies.Strategy
	strategyName := os.Getenv("STRATEGY")
	if strategyName == "" {
		strategyName = "Sway" // Default strategy
	}

	// Load pre-trained risk scores from static configuration
	// This must happen before strategy initialization so risk-based position sizing works
	if err := config.LoadRiskScores(); err != nil {
		log.Printf("⚠️  Warning: Failed to load risk scores: %v\n", err)
		log.Printf("⚠️  Trading will proceed but risk adjustment will not be applied\n")
	} else {
		log.Printf("✅ Risk scores loaded successfully - position sizing will be adjusted by hour\n")
	}

	switch strategyName {
	case "TwoSide":
		strategy = strategies.NewTwoSideStrategy(tradingEngine)
	case "LateEntry":
		strategy = strategies.NewLateEntryStrategy(tradingEngine)
	case "Sway":
		fallthrough
	default:
		strategy = strategies.NewSwayStrategy(tradingEngine)
	}
	log.Printf("✅ Strategy loaded: %s\n", strategy.Name())

	// Create and initialize dashboard
	dashboard := analytics.NewDashboard(tradingEngine.GetBalance())
	if strategyWithDashboard, ok := strategy.(interface{ SetDashboard(*analytics.Dashboard) }); ok {
		strategyWithDashboard.SetDashboard(dashboard)
	}

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

	// Run continuously. Tick every second so the strategy re-evaluates (and can
	// fire a fresh model prediction) every second the market is in its entry
	// window, rather than only at coarse checkpoints. Market data itself is
	// fetched on the fetcher's own PollIntervalSeconds cadence.
	ticker := time.NewTicker(1 * time.Second)
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
			// Update dashboard with current balance and risk state
			if dashboard != nil && tradingEngine != nil {
				dashboard.SetBalance(tradingEngine.GetBalance())
				
				// Update risk state on the dashboard
				if strategyWithRisk, ok := strategy.(interface{ UpdateDashboardRiskState() }); ok {
					strategyWithRisk.UpdateDashboardRiskState()
				}
				
				// Update market data in dashboard
				books := fetcher.GetAllLatestBooks()
				
				for cacheKey, book := range books {
					if book != nil {
						midPrice := (book.BestBidParsed + book.BestAskParsed) / 2
						var spread float64
						if midPrice > 0 {
							spread = ((book.BestAskParsed - book.BestBidParsed) / midPrice) * 100
						}
						dashboard.UpdateMarketData(cacheKey, book.BestBidParsed, book.BestBidSizeParsed, 
							book.BestAskParsed, book.BestAskSizeParsed, book.LiquidityParsed, spread)
					}
				}
				
				dashboard.Render()
			}

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

			// Get market books
			books := fetcher.GetAllLatestBooks()

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
						strategy.OnOrderPlaced(signal.MarketID, signal.Side, signal.Price, signal.Size)
					}
				}
			}
		}
	}
}
