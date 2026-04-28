package strategies

import (
	"log"
	"math"
	"time"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// LateEntryUpDownStrategy prioritizes small safe wins towards the end of a 5-minute market window
// Trades both UP and DOWN outcomes
// The strategy:
// 1. Waits until less than 1 minute remains
// 2. Looks for high price confidence (0.80-0.90) for safe small wins on both outcomes
// 3. In the last few seconds, aggressively buys any available shares if confidence reaches 0.98-0.99
// 4. Increases price check frequency for responsiveness
type LateEntryUpDownStrategy struct {
	*BaseStrategy
	windowStartTime time.Time
	lastCheckTime   time.Time
	lastTradeTime   time.Time
	positionsThisWindow map[string]bool // Track if we've already traded this market this window
	minBuyPrice float64                  // Minimum price to buy (only buy high confidence: 0.75+)
	maxSellPrice float64                 // Maximum price to sell short (only sell at very low: 0.25-)
	minWinConfidence float64             // Minimum confidence to trade in final minute (0.75 = 25% distance from 0.50)
	extremeConfidence float64            // Extreme confidence for last-second trades (0.98+)
}

// NewLateEntryUpDownStrategy creates a new late entry strategy that trades both UP and DOWN
func NewLateEntryUpDownStrategy(engine *trading.PaperTradingEngine) *LateEntryUpDownStrategy {
	log.Printf("Initializing LateEntryUpDownStrategy with parameters: minBuyPrice=%.2f, maxSellPrice=%.2f, minWinConfidence=%.2f, extremeConfidence=%.2f",
		0.75, 0.25, 0.75, 0.98)
	strategy := &LateEntryUpDownStrategy{
		BaseStrategy:        NewBaseStrategy(engine),
		windowStartTime:     time.Now(),
		lastCheckTime:       time.Now(),
		positionsThisWindow: make(map[string]bool),
		minBuyPrice:         0.75,        // Only buy when very high confidence (0.75+)
		maxSellPrice:        0.25,        // Only sell when very low (0.25-) - avoid low confidence shorts
		minWinConfidence:    0.75,        // 25% distance from 0.50 midpoint
		extremeConfidence:   0.98,        // Only trade at extreme certainty
	}
	// Override max position size for this strategy
	strategy.Config.MaxPositionSize = 100.0
	return strategy
}

// Name returns the strategy name
func (leud *LateEntryUpDownStrategy) Name() string {
	return "LateEntryUpDown"
}

// EvaluateV2 analyzes market data and returns complete trading signal
// Strategy logic:
// 1. Wait until less than 1 minute (60 seconds) remains in the window
// 2. Check prices frequently for responsiveness
// 3. ONLY trade when confidence is VERY HIGH (0.75+, 25% distance from 0.50)
// 4. BUY UP/DOWN only when price is 0.75+
// 5. SELL UP/DOWN only when price is 0.25- (avoid medium confidence shorts which lose)
// 6. In final seconds: Buy/Sell aggressively at extreme confidence (0.98+)
// 7. Trade both UP and DOWN outcomes
func (leud *LateEntryUpDownStrategy) EvaluateV2(markets map[string]*polymarket.MarketBook) *TradeSignal {
	
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

	leud.lastCheckTime = time.Now()

	// Log every check that passes the frequency gate
	log.Printf("[LateEntryUpDown] EVALUATE - Window: %ds into 300s (%d seconds remaining)", secondsIntoWindow, secondsRemaining)

	// Only trade in the final minute (< 60 seconds remaining)
	if secondsRemaining >= 60 {
		log.Printf("[LateEntryUpDown]   → Too early to trade (need < 60 seconds remaining)")
		return &TradeSignal{ShouldTrade: false}
	}
	
	log.Printf("[LateEntryUpDown]   → FINAL MINUTE! %d seconds remaining - checking markets...", secondsRemaining)

	// Look through available markets for trading opportunities
	for cacheKey, book := range markets {
		if book == nil {
			continue
		}

		// Determine outcome (UP or DOWN) from cache key
		var outcome string
		var marketID string
		
		if len(cacheKey) >= 3 && cacheKey[len(cacheKey)-2:] == "UP" {
			outcome = "UP"
			marketID = cacheKey[:len(cacheKey)-3]
		} else if len(cacheKey) >= 5 && cacheKey[len(cacheKey)-4:] == "DOWN" {
			outcome = "DOWN"
			marketID = cacheKey[:len(cacheKey)-5]
		} else {
			continue
		}

		// Create a unique position key that includes outcome
		positionKey := marketID + "-" + outcome

		// Log market state
		log.Printf("[LateEntryUpDown] %s (%s): Market state - Bid: %.4f (size: %.1f), Ask: %.4f (size: %.1f), Liquidity: %.0f", 
			marketID, outcome, book.BestBidParsed, book.BestBidSizeParsed, book.BestAskParsed, book.BestAskSizeParsed, book.LiquidityParsed)

		// Check for valid prices - we need at least one side with a valid price
		if book.BestBidParsed == 0 && book.BestAskParsed == 0 {
			log.Printf("[LateEntryUpDown] %s (%s): Skipped - both bid and ask are 0", marketID, outcome)
			continue
		}

		// Check liquidity requirement
		if book.LiquidityParsed < leud.Config.MinLiquidityUSDC {
			log.Printf("[LateEntryUpDown] %s (%s): Skipped - Liquidity %.0f < %.0f (required)", marketID, outcome, book.LiquidityParsed, leud.Config.MinLiquidityUSDC)
			continue
		}

		// Skip if we already traded this specific outcome this window
		if leud.positionsThisWindow[positionKey] {
			log.Printf("[LateEntryUpDown] %s (%s): Skipped - Already traded this outcome this window", marketID, outcome)
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
			if spreadPercent < leud.Config.MinSpread || spreadPercent > leud.Config.MaxSpread {
				log.Printf("[LateEntryUpDown] %s (%s): Skipped - Spread %.2f%% outside range [%.2f%%, %.2f%%]", marketID, outcome, spreadPercent, leud.Config.MinSpread, leud.Config.MaxSpread)
				continue
			}
		} else {
			log.Printf("[LateEntryUpDown] %s (%s): One-sided market (bid=%.4f, ask=%.4f) - allowing wide spread", marketID, outcome, book.BestBidParsed, book.BestAskParsed)
		}

		log.Printf("[LateEntryUpDown] %s (%s): Evaluating - Price: %.4f, Spread: %.2f%%, Liquidity: %.0f", marketID, outcome, midPrice, spreadPercent, book.LiquidityParsed)

		inFinalSeconds := secondsRemaining < 10

		// Check all conditions for this data point
		extremeHighMet := midPrice >= leud.extremeConfidence
		extremeLowMet := midPrice <= (1.0 - leud.extremeConfidence)
		highConfBuyMet := midPrice >= leud.minBuyPrice
		lowConfSellMet := midPrice <= leud.maxSellPrice
		minSizeForBuy := math.Min(
			leud.Config.MaxPositionSize / book.BestAskParsed,
			book.BestAskSizeParsed*0.75,
		) > 0.5
		minSizeForSell := math.Min(
			leud.Config.MaxPositionSize / book.BestBidParsed,
			book.BestBidSizeParsed*0.75,
		) > 0.5
		minSizeForConservativeBuy := math.Min(
			(leud.Config.MaxPositionSize * 0.3) / book.BestAskParsed,
			book.BestAskSizeParsed*0.2,
		) > 0.5
		minSizeForConservativeSell := math.Min(
			(leud.Config.MaxPositionSize * 0.2) / book.BestBidParsed,
			book.BestBidSizeParsed*0.1,
		) > 0.5

		// Log all conditions
		log.Printf("[LateEntryUpDown] %s (%s): CONDITIONS @ %ds remaining:", marketID, outcome, secondsRemaining)
		log.Printf("  [%v] In final seconds (<%d)           | inFinalSeconds=%v", boolToCheck(inFinalSeconds), 10, inFinalSeconds)
		log.Printf("  [%v] Extreme high confidence (≥%.4f)   | price=%.4f", boolToCheck(extremeHighMet), leud.extremeConfidence, midPrice)
		log.Printf("  [%v] Extreme low confidence (≤%.4f)    | price=%.4f", boolToCheck(extremeLowMet), 1.0-leud.extremeConfidence, midPrice)
		log.Printf("  [%v] High confidence BUY (≥%.4f)      | price=%.4f", boolToCheck(highConfBuyMet), leud.minBuyPrice, midPrice)
		log.Printf("  [%v] Low confidence SELL (≤%.4f)      | price=%.4f", boolToCheck(lowConfSellMet), leud.maxSellPrice, midPrice)
		log.Printf("  [%v] Size OK for extreme BUY (%.1f)    | extremeSize=%.0f", boolToCheck(minSizeForBuy), 0.5, math.Min(leud.Config.MaxPositionSize/book.BestAskParsed, book.BestAskSizeParsed*0.75))
		log.Printf("  [%v] Size OK for extreme SELL (%.1f)   | extremeSize=%.0f", boolToCheck(minSizeForSell), 0.5, math.Min(leud.Config.MaxPositionSize/book.BestBidParsed, book.BestBidSizeParsed*0.75))
		log.Printf("  [%v] Size OK for conservative BUY (%.1f) | conservativeSize=%.0f", boolToCheck(minSizeForConservativeBuy), 0.5, math.Min((leud.Config.MaxPositionSize*0.3)/book.BestAskParsed, book.BestAskSizeParsed*0.2))
		log.Printf("  [%v] Size OK for conservative SELL (%.1f) | conservativeSize=%.0f", boolToCheck(minSizeForConservativeSell), 0.5, math.Min((leud.Config.MaxPositionSize*0.2)/book.BestBidParsed, book.BestBidSizeParsed*0.1))

		// STRATEGY 1: Final seconds - aggressive trading at extreme confidence (0.98+)
		if inFinalSeconds {
			log.Printf("[LateEntryUpDown] %s (%s): FINAL SECONDS - checking for extreme confidence...", marketID, outcome)
			// Only trade at extreme certainty: 0.98+ or 0.02-
			if extremeHighMet && minSizeForBuy {
				// Outcome is near certain - BUY it
				positionSize := math.Min(
					leud.Config.MaxPositionSize / book.BestAskParsed,
					book.BestAskSizeParsed*0.75,
				)
				log.Printf("[LateEntryUpDown] %s (%s): ✓ SIGNAL - BUY (extreme high: %.4f >= %.4f), size: %.0f", marketID, outcome, midPrice, leud.extremeConfidence, positionSize)
				if positionSize > 0.5 {
					leud.lastTradeTime = time.Now()
					leud.positionsThisWindow[positionKey] = true
					return &TradeSignal{
						ShouldTrade:        true,
						MarketID:           marketID,
						Side:               "BUY",
						Price:              book.BestAskParsed,
						Size:               positionSize,
						AvailableLiquidity: book.BestAskSizeParsed,
						Outcome:            outcome,
					}
				}
			}

			if extremeLowMet && minSizeForSell {
				// Outcome is near certain to lose - SELL it (short)
				positionSize := math.Min(
					leud.Config.MaxPositionSize / book.BestBidParsed,
					book.BestBidSizeParsed*0.75,
				)
				log.Printf("[LateEntryUpDown] %s (%s): ✓ SIGNAL - SELL (extreme low: %.4f <= %.4f), size: %.0f", marketID, outcome, midPrice, 1.0-leud.extremeConfidence, positionSize)
				if positionSize > 0.5 {
					leud.lastTradeTime = time.Now()
					leud.positionsThisWindow[positionKey] = true
					return &TradeSignal{
						ShouldTrade:        true,
						MarketID:           marketID,
						Side:               "SELL",
						Price:              book.BestBidParsed,
						Size:               positionSize,
						AvailableLiquidity: book.BestBidSizeParsed,
						Outcome:            outcome,
					}
				}
			}
		}

		// STRATEGY 2: Final minute - only high confidence (0.75+), small positions, conservative sizing
		// Based on performance data: 0.82-0.86 BUY entries work great
		// LOW confidence shorts (0.15-0.17) are disaster - avoid them

		// BUY: Only when price is very high (0.75+)
		if highConfBuyMet && minSizeForConservativeBuy {
			// Conservative position size for high-confidence buys
			positionSize := math.Min(
				(leud.Config.MaxPositionSize * 0.3) / book.BestAskParsed, // Only 30% of max
				book.BestAskSizeParsed*0.2, // Take only 20% of liquidity
			)
			log.Printf("[LateEntryUpDown] %s (%s): ✓ SIGNAL - BUY (high conf: %.4f >= %.4f), size: %.0f", marketID, outcome, midPrice, leud.minBuyPrice, positionSize)
			if positionSize > 0.5 {
				leud.lastTradeTime = time.Now()
				leud.positionsThisWindow[positionKey] = true
				return &TradeSignal{
					ShouldTrade:        true,
					MarketID:           marketID,
					Side:               "BUY",
					Price:              book.BestAskParsed,
					Size:               positionSize,
					AvailableLiquidity: book.BestAskSizeParsed,
					Outcome:            outcome,
				}
			}
		}

		// SELL: Only when price is very low (0.25-) - AVOID medium confidence shorts
		if lowConfSellMet && minSizeForConservativeSell {
			// Very conservative position size for shorts
			positionSize := math.Min(
				(leud.Config.MaxPositionSize * 0.2) / book.BestBidParsed, // Only 20% of max
				book.BestBidSizeParsed*0.1, // Take only 10% of liquidity
			)
			log.Printf("[LateEntryUpDown] %s (%s): ✓ SIGNAL - SELL (low conf: %.4f <= %.4f), size: %.0f", marketID, outcome, midPrice, leud.maxSellPrice, positionSize)
			if positionSize > 0.5 {
				leud.lastTradeTime = time.Now()
				leud.positionsThisWindow[positionKey] = true
				return &TradeSignal{
					ShouldTrade:        true,
					MarketID:           marketID,
					Side:               "SELL",
					Price:              book.BestBidParsed,
					Size:               positionSize,
					AvailableLiquidity: book.BestBidSizeParsed,
					Outcome:            outcome,
				}
			}
		}
	}

	return &TradeSignal{ShouldTrade: false}
}

// OnOrderPlaced is called after an order is executed
func (leud *LateEntryUpDownStrategy) OnOrderPlaced(marketID string, side string, price float64, size float64) {
	// Could log trades or update statistics here
}

// OnMarketWindowChange is called when a new 5-minute window begins
func (leud *LateEntryUpDownStrategy) OnMarketWindowChange() {
	leud.windowStartTime = time.Now()
	leud.lastCheckTime = time.Now()
	leud.positionsThisWindow = make(map[string]bool) // Reset for new window
}

// Reset clears internal state
func (leud *LateEntryUpDownStrategy) Reset() {
	leud.windowStartTime = time.Now()
	leud.lastCheckTime = time.Now()
	leud.positionsThisWindow = make(map[string]bool)
	leud.lastTradeTime = time.Time{} // Reset last trade time
}
