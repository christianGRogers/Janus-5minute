package strategies

import (
	"log"
	"math"
	"time"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// LateEntryUpOnlyStrategy prioritizes small safe wins towards the end of a 5-minute market window
// The strategy:
// 1. Waits until less than 1 minute remains
// 2. Looks for high price confidence (0.80-0.90) for safe small wins
// 3. In the last few seconds, aggressively buys any available shares if confidence reaches 0.98-0.99
// 4. Increases price check frequency for responsiveness
// 5. ONLY places BUY orders - never shorts (no SELL orders)
type LateEntryUpOnlyStrategy struct {
	*BaseStrategy
	windowStartTime time.Time
	lastCheckTime   time.Time
	lastTradeTime   time.Time
	positionsThisWindow map[string]bool // Track if we've already traded this market this window
	minBuyPrice float64                  // Minimum price to buy UP (only buy high confidence: 0.75+)
	minWinConfidence float64             // Minimum confidence to trade in final minute (0.75 = 25% distance from 0.50)
	extremeConfidence float64            // Extreme confidence for last-second trades (0.98+)
}

// NewLateEntryUpOnlyStrategy creates a new late entry up-only strategy
func NewLateEntryUpOnlyStrategy(engine trading.TradingEngine) *LateEntryUpOnlyStrategy {
	log.Printf("Initializing LateEntryUpOnlyStrategy with parameters: minBuyPrice=%.2f, minWinConfidence=%.2f, extremeConfidence=%.2f (UP ONLY - NO SHORTS)",
		0.75, 0.75, 0.98)
	strategy := &LateEntryUpOnlyStrategy{
		BaseStrategy:        NewBaseStrategy(engine),
		windowStartTime:     time.Now(),
		lastCheckTime:       time.Now(),
		positionsThisWindow: make(map[string]bool),
		minBuyPrice:         0.75,        // Only buy UP when very high confidence (0.75+)
		minWinConfidence:    0.75,        // 25% distance from 0.50 midpoint
		extremeConfidence:   0.98,        // Only trade at extreme certainty
	}
	// Use 100% risk tolerance: can risk up to 100% of current balance per trade
	// This means if balance is $20, a single trade can be up to $20
	// If balance is $100, a single trade can be up to $100
	strategy.Config.RiskTolerance = 0.4
	strategy.Config.MaxPositionSize = 0 // Disable fixed max, use dynamic sizing
	return strategy
}

// Name returns the strategy name
func (les *LateEntryUpOnlyStrategy) Name() string {
	return "LateEntryUpOnly"
}

// EvaluateV2 analyzes market data and returns complete trading signal
// Strategy logic:
// 1. Wait until less than 1 minute (60 seconds) remains in the window
// 2. Check prices frequently for responsiveness
// 3. ONLY trade when confidence is VERY HIGH (0.75+, 25% distance from 0.50)
// 4. BUY only when UP price is 0.75+
// 5. NEVER sell or short - only buy UP shares
// 6. In final seconds: Buy aggressively at extreme confidence (0.98+)
func (les *LateEntryUpOnlyStrategy) EvaluateV2(markets map[string]*polymarket.MarketBook) *TradeSignal {
	
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
	// timeSinceLastCheck := time.Since(les.lastCheckTime)
	// if timeSinceLastCheck < 500*time.Millisecond {
	// 	// Early return - too soon to check again (silent, no logging)
	// 	return false, "", "", 0, 0
	// }
	les.lastCheckTime = time.Now()

	// Log every check that passes the frequency gate
	log.Printf("[LateEntryUpOnly] EVALUATE - Window: %ds into 300s (%d seconds remaining)", secondsIntoWindow, secondsRemaining)

	// Only trade in the final minute (< 60 seconds remaining)
	if secondsRemaining >= 60 {
		log.Printf("[LateEntryUpOnly]   → Too early to trade (need < 60 seconds remaining)")
		return &TradeSignal{ShouldTrade: false}
	}
	
	log.Printf("[LateEntryUpOnly]   → FINAL MINUTE! %d seconds remaining - checking markets...", secondsRemaining)

	// Look through available markets for trading opportunities
	for cacheKey, book := range markets {
		if book == nil {
			continue
		}

		// Only trade UP outcomes (cache key ends with -UP)
		if len(cacheKey) < 3 || cacheKey[len(cacheKey)-2:] != "UP" {
			continue
		}

		// Extract market ID (remove -UP suffix)
		marketID := cacheKey[:len(cacheKey)-3]

		// Log market state
		log.Printf("[LateEntryUpOnly] %s: Market state - Bid: %.4f (size: %.1f), Ask: %.4f (size: %.1f), Liquidity: %.0f", 
			marketID, book.BestBidParsed, book.BestBidSizeParsed, book.BestAskParsed, book.BestAskSizeParsed, book.LiquidityParsed)

		// Check for valid prices - we need at least one side with a valid price
		if book.BestBidParsed == 0 && book.BestAskParsed == 0 {
			log.Printf("[LateEntryUpOnly] %s: Skipped - both bid and ask are 0", marketID)
			continue
		}

		// Check liquidity requirement
		if book.LiquidityParsed < les.Config.MinLiquidityUSDC {
			log.Printf("[LateEntryUpOnly] %s: Skipped - Liquidity %.0f < %.0f (required)", marketID, book.LiquidityParsed, les.Config.MinLiquidityUSDC)
			continue
		}

		// Skip if we already traded this market this window
		if les.positionsThisWindow[marketID] {
			log.Printf("[LateEntryUpOnly] %s: Skipped - Already traded this window", marketID)
			continue
		}

		// Calculate mid price and spread - handle cases where one side is 0
		var midPrice float64
		if book.BestBidParsed > 0 && book.BestAskParsed > 0 {
			midPrice = (book.BestBidParsed + book.BestAskParsed) / 2
		} else if book.BestBidParsed > 0 {
			midPrice = book.BestBidParsed
		} else {
			midPrice = book.BestAskParsed
		}

		var spreadPercent float64
		if midPrice > 0 {
			spreadPercent = ((book.BestAskParsed - book.BestBidParsed) / midPrice) * 100
		}

		// For one-sided markets (ask=0 or bid=0), allow larger spreads
		// Only enforce strict spread limits when both sides have prices
		if book.BestBidParsed > 0 && book.BestAskParsed > 0 {
			if spreadPercent < les.Config.MinSpread || spreadPercent > les.Config.MaxSpread {
				log.Printf("[LateEntryUpOnly] %s: Skipped - Spread %.2f%% outside range [%.2f%%, %.2f%%]", marketID, spreadPercent, les.Config.MinSpread, les.Config.MaxSpread)
				continue
			}
		} else {
			log.Printf("[LateEntryUpOnly] %s: One-sided market (bid=%.4f, ask=%.4f) - allowing wide spread", marketID, book.BestBidParsed, book.BestAskParsed)
		}

		log.Printf("[LateEntryUpOnly] %s: Evaluating - Price: %.4f, Spread: %.2f%%, Liquidity: %.0f", marketID, midPrice, spreadPercent, book.LiquidityParsed)

		inFinalSeconds := secondsRemaining < 10
		
		// Get dynamic position size based on current balance and risk tolerance
		maxPosSize := les.GetDynamicPositionSize()

		// Check all conditions for this data point
		extremeHighMet := midPrice >= les.extremeConfidence
		highConfBuyMet := midPrice >= les.minBuyPrice
		minSizeForBuy := math.Min(
			maxPosSize / book.BestAskParsed,
			book.BestAskSizeParsed*0.75,
		) > 0.5
		minSizeForConservativeBuy := math.Min(
			(maxPosSize * 0.3) / book.BestAskParsed,
			book.BestAskSizeParsed*0.2,
		) > 0.5

		// Log all conditions
		log.Printf("[LateEntryUpOnly] %s: CONDITIONS @ %ds remaining (maxPosSize: $%.2f):", marketID, secondsRemaining, maxPosSize)
		log.Printf("  [%v] In final seconds (<%d)           | inFinalSeconds=%v", boolToCheck(inFinalSeconds), 10, inFinalSeconds)
		log.Printf("  [%v] Extreme high confidence (≥%.4f)   | price=%.4f", boolToCheck(extremeHighMet), les.extremeConfidence, midPrice)
		log.Printf("  [%v] High confidence BUY (≥%.4f)      | price=%.4f", boolToCheck(highConfBuyMet), les.minBuyPrice, midPrice)
		log.Printf("  [%v] Size OK for extreme BUY (%.1f)    | extremeSize=%.0f", boolToCheck(minSizeForBuy), 0.5, math.Min(maxPosSize/book.BestAskParsed, book.BestAskSizeParsed*0.75))
		log.Printf("  [%v] Size OK for conservative BUY (%.1f) | conservativeSize=%.0f", boolToCheck(minSizeForConservativeBuy), 0.5, math.Min((maxPosSize*0.3)/book.BestAskParsed, book.BestAskSizeParsed*0.2))

		// STRATEGY 1: Final seconds - aggressive trading at extreme confidence (0.98+)
		if inFinalSeconds {
			log.Printf("[LateEntryUpOnly] %s: FINAL SECONDS - checking for extreme confidence...", marketID)
			// Only trade at extreme certainty: 0.98+
			if extremeHighMet && minSizeForBuy {
				// UP is near certain - BUY it
				positionSize := math.Min(
					maxPosSize / book.BestAskParsed,
					book.BestAskSizeParsed*0.75,
				)
				log.Printf("[LateEntryUpOnly] %s: ✓ SIGNAL - BUY (extreme high: %.4f >= %.4f), size: %.0f", marketID, midPrice, les.extremeConfidence, positionSize)
				if positionSize > 0.5 {
					les.lastTradeTime = time.Now()
					les.positionsThisWindow[marketID] = true
					return &TradeSignal{
						ShouldTrade:        true,
						MarketID:           marketID,
						Side:               "BUY",
						Price:              book.BestAskParsed,
						Size:               positionSize,
						AvailableLiquidity: book.BestAskSizeParsed,
						Outcome:            "UP",
					}
				}
			}
		}

		// STRATEGY 2: Final minute - only high confidence (0.75+), small positions, conservative sizing
		// Based on performance data: 0.82-0.86 BUY entries work great
		// ONLY BUY - NO SHORTS

		// BUY: Only when UP price is very high (0.75+)
		if highConfBuyMet && minSizeForConservativeBuy {
			// Conservative position size for high-confidence buys
			positionSize := math.Min(
				(maxPosSize * 0.3) / book.BestAskParsed, // Only 30% of max
				book.BestAskSizeParsed*0.2, // Take only 20% of liquidity
			)
			log.Printf("[LateEntryUpOnly] %s: ✓ SIGNAL - BUY (high conf: %.4f >= %.4f), size: %.0f", marketID, midPrice, les.minBuyPrice, positionSize)
			if positionSize > 0.5 {
				les.lastTradeTime = time.Now()
				les.positionsThisWindow[marketID] = true
				return &TradeSignal{
					ShouldTrade:        true,
					MarketID:           marketID,
					Side:               "BUY",
					Price:              book.BestAskParsed,
					Size:               positionSize,
					AvailableLiquidity: book.BestAskSizeParsed,
					Outcome:            "UP",
				}
			}
		}
	}

	return &TradeSignal{ShouldTrade: false}
}

// OnOrderPlaced is called after an order is executed
func (les *LateEntryUpOnlyStrategy) OnOrderPlaced(marketID string, side string, price float64, size float64) {
	// Could log trades or update statistics here
}

// OnMarketWindowChange is called when a new 5-minute window begins
func (les *LateEntryUpOnlyStrategy) OnMarketWindowChange() {
	les.windowStartTime = time.Now()
	les.lastCheckTime = time.Now()
	les.positionsThisWindow = make(map[string]bool) // Reset for new window
}

// Reset clears internal state
func (les *LateEntryUpOnlyStrategy) Reset() {
	les.windowStartTime = time.Now()
	les.lastCheckTime = time.Now()
	les.positionsThisWindow = make(map[string]bool)
	les.lastTradeTime = time.Time{} // Reset last trade time
}
