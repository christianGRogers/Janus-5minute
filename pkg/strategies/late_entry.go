package strategies

import (
	"log"
	"math"
	"time"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// LateEntryStrategy prioritizes small safe wins towards the end of a 5-minute market window
// The strategy:
// 1. Waits until less than 1 minute remains
// 2. Looks for high price confidence (0.80-0.90) for safe small wins
// 3. In the last few seconds, aggressively buys any available shares if confidence reaches 0.98-0.99
// 4. Increases price check frequency for responsiveness
type LateEntryStrategy struct {
	*BaseStrategy
	windowStartTime time.Time
	lastCheckTime   time.Time
	lastTradeTime   time.Time
	positionsThisWindow map[string]bool // Track if we've already traded this market this window
	minBuyPrice float64                  // Minimum price to buy UP (only buy high confidence: 0.75+)
	maxSellPrice float64                 // Maximum price to sell UP short (only sell at very low: 0.25-)
	minWinConfidence float64             // Minimum confidence to trade in final minute (0.75 = 25% distance from 0.50)
	extremeConfidence float64            // Extreme confidence for last-second trades (0.98+)
}

// NewLateEntryStrategy creates a new late entry strategy
func NewLateEntryStrategy(engine *trading.PaperTradingEngine) *LateEntryStrategy {
	return &LateEntryStrategy{
		BaseStrategy:        NewBaseStrategy(engine),
		windowStartTime:     time.Now(),
		lastCheckTime:       time.Now(),
		positionsThisWindow: make(map[string]bool),
		minBuyPrice:         0.75,        // Only buy UP when very high confidence (0.75+)
		maxSellPrice:        0.25,        // Only sell UP when very low (0.25-) - avoid low confidence shorts
		minWinConfidence:    0.75,        // 25% distance from 0.50 midpoint
		extremeConfidence:   0.98,        // Only trade at extreme certainty
	}
}

// Name returns the strategy name
func (les *LateEntryStrategy) Name() string {
	return "LateEntry"
}

// Evaluate analyzes market data and returns trading signals
// Strategy logic:
// 1. Wait until less than 1 minute (60 seconds) remains in the window
// 2. Check prices frequently for responsiveness
// 3. ONLY trade when confidence is VERY HIGH (0.75+, 25% distance from 0.50)
// 4. BUY only when UP price is 0.75+
// 5. SELL only when UP price is 0.25- (avoid medium confidence shorts which lose)
// 6. In final seconds: Buy/Sell aggressively at extreme confidence (0.98+)
func (les *LateEntryStrategy) Evaluate(markets map[string]*polymarket.MarketBook) (bool, string, string, float64, float64) {
	// Calculate the ACTUAL 5-minute market window based on current time
	// Markets are in 300-second (5-minute) windows: 0:00-4:59, 5:00-9:59, etc.
	now := time.Now()
	currentWindowNumber := now.Unix() / 300      // Which 5-minute window are we in?
	windowStartUnix := currentWindowNumber * 300  // Timestamp of this window's start
	windowStartTime := time.Unix(windowStartUnix, 0)
	
	// Calculate time remaining in the 5-minute window
	timeSinceWindowStart := now.Sub(windowStartTime)
	secondsIntoWindow := int(timeSinceWindowStart.Seconds())
	secondsRemaining := 300 - secondsIntoWindow // 5 minutes = 300 seconds

	// Increase check frequency: check every 0.5 seconds
	if time.Since(les.lastCheckTime) < 500*time.Millisecond {
		return false, "", "", 0, 0
	}
	les.lastCheckTime = time.Now()

	// Only trade in the final minute (< 60 seconds remaining)
	if secondsRemaining >= 60 {
		// Only log every 10 seconds to avoid spam
		if secondsIntoWindow%10 == 0 {
			log.Printf("[LateEntry] Window: %ds into 300s (%.1f min remaining) - Too early to trade", secondsIntoWindow, float64(secondsRemaining)/60.0)
		}
		return false, "", "", 0, 0
	}
	
	log.Printf("[LateEntry] Final minute! %ds remaining", secondsRemaining)

	// Look through available markets for trading opportunities
	for cacheKey, book := range markets {
		if book == nil || book.BestBidParsed == 0 || book.BestAskParsed == 0 {
			continue
		}

		// Only trade UP outcomes (cache key ends with -UP)
		if len(cacheKey) < 3 || cacheKey[len(cacheKey)-2:] != "UP" {
			continue
		}

		// Extract market ID (remove -UP suffix)
		marketID := cacheKey[:len(cacheKey)-3]

		// Check liquidity requirement
		if book.LiquidityParsed < les.Config.MinLiquidityUSDC {
			log.Printf("[LateEntry] %s: Liquidity %.0f < %.0f (required)", marketID, book.LiquidityParsed, les.Config.MinLiquidityUSDC)
			continue
		}

		// Skip if we already traded this market this window
		if les.positionsThisWindow[marketID] {
			log.Printf("[LateEntry] %s: Already traded this window", marketID)
			continue
		}

		// Calculate spread percentage
		midPrice := (book.BestBidParsed + book.BestAskParsed) / 2
		spreadPercent := ((book.BestAskParsed - book.BestBidParsed) / midPrice) * 100

		// Only trade if spread is reasonable
		if spreadPercent < les.Config.MinSpread || spreadPercent > les.Config.MaxSpread {
			log.Printf("[LateEntry] %s: Spread %.2f%% outside range [%.2f%%, %.2f%%]", marketID, spreadPercent, les.Config.MinSpread, les.Config.MaxSpread)
			continue
		}

		log.Printf("[LateEntry] %s: Evaluating - Price: %.4f, Spread: %.2f%%, Liquidity: %.0f", marketID, midPrice, spreadPercent, book.LiquidityParsed)

		inFinalSeconds := secondsRemaining < 10

		// STRATEGY 1: Final seconds - aggressive trading at extreme confidence (0.98+)
		if inFinalSeconds {
			log.Printf("[LateEntry] %s: Final seconds (<%ds) - checking for extreme confidence", marketID, 10)
			// Only trade at extreme certainty: 0.98+ or 0.02-
			if midPrice >= les.extremeConfidence {
				// UP is near certain - BUY it
				positionSize := math.Min(
					les.Config.MaxPositionSize / book.BestAskParsed,
					book.BestAskSizeParsed*0.75,
				)
				log.Printf("[LateEntry] %s: SIGNAL - BUY (extreme high: %.4f >= %.4f), size: %.0f", marketID, midPrice, les.extremeConfidence, positionSize)
				if positionSize > 0.5 {
					les.lastTradeTime = time.Now()
					les.positionsThisWindow[marketID] = true
					return true, marketID, "BUY", book.BestAskParsed, positionSize
				}
			}

			if midPrice <= (1.0 - les.extremeConfidence) {
				// UP is near certain to lose - SELL it (short)
				positionSize := math.Min(
					les.Config.MaxPositionSize / book.BestBidParsed,
					book.BestBidSizeParsed*0.75,
				)
				log.Printf("[LateEntry] %s: SIGNAL - SELL (extreme low: %.4f <= %.4f), size: %.0f", marketID, midPrice, 1.0-les.extremeConfidence, positionSize)
				if positionSize > 0.5 {
					les.lastTradeTime = time.Now()
					les.positionsThisWindow[marketID] = true
					return true, marketID, "SELL", book.BestBidParsed, positionSize
				}
			}
		}

		// STRATEGY 2: Final minute - only high confidence (0.75+), small positions, conservative sizing
		// Based on performance data: 0.82-0.86 BUY entries work great
		// LOW confidence shorts (0.15-0.17) are disaster - avoid them

		// BUY: Only when UP price is very high (0.75+)
		if midPrice >= les.minBuyPrice {
			// Conservative position size for high-confidence buys
			positionSize := math.Min(
				(les.Config.MaxPositionSize * 0.3) / book.BestAskParsed, // Only 30% of max
				book.BestAskSizeParsed*0.2, // Take only 20% of liquidity
			)
			log.Printf("[LateEntry] %s: SIGNAL - BUY (high conf: %.4f >= %.4f), size: %.0f", marketID, midPrice, les.minBuyPrice, positionSize)
			if positionSize > 0.5 {
				les.lastTradeTime = time.Now()
				les.positionsThisWindow[marketID] = true
				return true, marketID, "BUY", book.BestAskParsed, positionSize
			}
		}

		// SELL: Only when UP price is very low (0.25-) - AVOID medium confidence shorts
		if midPrice <= les.maxSellPrice {
			// Very conservative position size for shorts
			positionSize := math.Min(
				(les.Config.MaxPositionSize * 0.2) / book.BestBidParsed, // Only 20% of max
				book.BestBidSizeParsed*0.1, // Take only 10% of liquidity
			)
			log.Printf("[LateEntry] %s: SIGNAL - SELL (low conf: %.4f <= %.4f), size: %.0f", marketID, midPrice, les.maxSellPrice, positionSize)
			if positionSize > 0.5 {
				les.lastTradeTime = time.Now()
				les.positionsThisWindow[marketID] = true
				return true, marketID, "SELL", book.BestBidParsed, positionSize
			}
		}
	}

	return false, "", "", 0, 0
}

// OnOrderPlaced is called after an order is executed
func (les *LateEntryStrategy) OnOrderPlaced(marketID string, side string, price float64, size float64) {
	// Could log trades or update statistics here
}

// OnMarketWindowChange is called when a new 5-minute window begins
func (les *LateEntryStrategy) OnMarketWindowChange() {
	les.windowStartTime = time.Now()
	les.lastCheckTime = time.Now()
	les.positionsThisWindow = make(map[string]bool) // Reset for new window
}

// Reset clears internal state
func (les *LateEntryStrategy) Reset() {
	les.windowStartTime = time.Now()
	les.lastCheckTime = time.Now()
	les.positionsThisWindow = make(map[string]bool)
	les.lastTradeTime = time.Time{} // Reset last trade time
}
