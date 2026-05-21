package strategies

import (
	"log"
	"math"
	"time"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// LateEntryStrategy prioritizes small safe wins towards the end of a 5-minute market window
// The strategy uses a two-tier system to avoid the "coin flip zone" (0.50-0.75):
// 1. Waits until less than 1 minute remains
// 2. AVOIDS medium confidence (0.50-0.75) - these cause 100% unmatched losses
// 3. HIGH confidence tier (0.80+): Small conservative buys when confident UP will win
// 4. EXTREME confidence tier (0.98+): Aggressive bets in final seconds only
// 5. CRITICAL: Tracks inventory - only allows SELL when shares are actually owned
type LateEntryStrategy struct {
	*BaseStrategy
	windowStartTime time.Time
	lastCheckTime   time.Time
	lastTradeTime   time.Time
	positionsThisWindow map[string]bool    // Track if we've already traded this market this window
	ownedInventory      map[string]float64 // Track shares owned by market ID (for proper sell gating)
	highConfThreshold   float64            // High confidence entry point: 0.75+ (avoid low buys)
	veryHighConfBuy     float64            // Very high confidence: 0.85+ (increased position size)
	extremeConfidence   float64            // Extreme confidence for last-second trades (0.98+)
	minHoldPrice        float64            // Minimum price to hold: 0.70 (exit/sell below this to minimize loss)
}

// NewLateEntryStrategy creates a new late entry strategy
func NewLateEntryStrategy(engine trading.TradingEngine) *LateEntryStrategy {
	log.Printf("Initializing LateEntryStrategy - BUY HIGH MODE: MinBuy=0.75+, PreferHigh=0.85+, ExtremeConf=0.98+, LossExit=0.70-")
	strategy := &LateEntryStrategy{
		BaseStrategy:        NewBaseStrategy(engine),
		windowStartTime:     time.Now(),
		lastCheckTime:       time.Now(),
		positionsThisWindow: make(map[string]bool),
		ownedInventory:      make(map[string]float64),
		highConfThreshold:   0.85,        // No buys below 0.85 - avoid medium confidence zone
		veryHighConfBuy:     0.95,        // Prefer higher confidence (0.95+) for better wins
		extremeConfidence:   0.98,        // Aggressive trading in final seconds
		minHoldPrice:        0.70,        // Sell inventory if price drops below 0.70 (loss minimization)
	}
	strategy.Config.RiskTolerance = 0.4
	strategy.Config.MaxPositionSize = 0 // Disable fixed max, use dynamic sizing
	return strategy
}

// Name returns the strategy name
func (les *LateEntryStrategy) Name() string {
	return "LateEntry"
}

// EvaluateV2 analyzes market data and returns complete trading signal
// BUY HIGH + LOSS EXIT STRATEGY:
// 1. Wait until less than 1 minute (60 seconds) remains in the window
// 2. NO buys below 0.75 - skip the medium confidence zone entirely
// 3. PREFER high confidence (0.85+) - these consistently win
// 4. TIER 1 (0.75-0.84): Conservative buys with small position sizes
// 5. TIER 2 (0.85+): Standard buys with larger position sizes
// 6. EXTREME (0.98+): Aggressive final-second trades
// 7. LOSS EXIT: SELL inventory if price drops below 0.70 (minimize losses)
func (les *LateEntryStrategy) EvaluateV2(markets map[string]*polymarket.MarketBook) *TradeSignal {
	
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
	log.Printf("[LateEntry] EVALUATE - Window: %ds into 300s (%d seconds remaining)", secondsIntoWindow, secondsRemaining)

	// Only trade in the final minute (< 60 seconds remaining)
	if secondsRemaining >= 60 {
		log.Printf("[LateEntry]   → Too early to trade (need < 60 seconds remaining)")
		return &TradeSignal{ShouldTrade: false}
	}
	
	// Allow trading if we're in final 1:30 (90 seconds) - either for general trading or high confidence buys
	allowTrading := secondsRemaining < 90
	
	if !allowTrading {
		log.Printf("[LateEntry]   → Too early to trade (need < 90 seconds remaining for high conf, or < 60 for standard)")
		return &TradeSignal{ShouldTrade: false}
	}
	
	log.Printf("[LateEntry]   → Within trading window! %d seconds remaining - checking markets...", secondsRemaining)

	// Look through available markets for trading opportunities
	for cacheKey, book := range markets {
		if book == nil {
			continue
		}

		// Determine if this is an UP or DOWN market
		var outcome string
		var marketID string
		
		if len(cacheKey) >= 3 && cacheKey[len(cacheKey)-2:] == "UP" {
			outcome = "UP"
			marketID = cacheKey[:len(cacheKey)-3]
		} else if len(cacheKey) >= 4 && cacheKey[len(cacheKey)-4:] == "DOWN" {
			outcome = "DOWN"
			marketID = cacheKey[:len(cacheKey)-5]
		} else {
			continue
		}

		// Log market state
		log.Printf("[LateEntry] %s: Market state - Bid: %.4f (size: %.1f), Ask: %.4f (size: %.1f), Liquidity: %.0f", 
			marketID, book.BestBidParsed, book.BestBidSizeParsed, book.BestAskParsed, book.BestAskSizeParsed, book.LiquidityParsed)

		// Check for valid prices - we need at least one side with a valid price
		if book.BestBidParsed == 0 && book.BestAskParsed == 0 {
			log.Printf("[LateEntry] %s: Skipped - both bid and ask are 0", marketID)
			continue
		}

		// Check liquidity requirement
		if book.LiquidityParsed < les.Config.MinLiquidityUSDC {
			log.Printf("[LateEntry] %s: Skipped - Liquidity %.0f < %.0f (required)", marketID, book.LiquidityParsed, les.Config.MinLiquidityUSDC)
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
				log.Printf("[LateEntry] %s: Skipped - Spread %.2f%% outside range [%.2f%%, %.2f%%]", marketID, spreadPercent, les.Config.MinSpread, les.Config.MaxSpread)
				continue
			}
		} else {
			log.Printf("[LateEntry] %s: One-sided market (bid=%.4f, ask=%.4f) - allowing wide spread", marketID, book.BestBidParsed, book.BestAskParsed)
		}

		log.Printf("[LateEntry] %s: Evaluating - Price: %.4f, Spread: %.2f%%, Liquidity: %.0f", marketID, midPrice, spreadPercent, book.LiquidityParsed)

		inFinalSeconds := secondsRemaining < 10
		inFinalMinute := secondsRemaining < 60
		
		// Get dynamic position size based on current balance and risk tolerance
		maxPosSize := les.GetDynamicPositionSize()

		// Check all conditions for this data point
		// For UP outcome: high price = good (buy when UP price is high)
		// For DOWN outcome: high price = good (buy when DOWN price is high)
		// Both use the same confidence thresholds - no inversion needed
		var extremeHighMet, highConfBuyMet, veryHighConfBuyMet, lossExitMet bool
		
		// Use midPrice directly for both outcomes - the market provides correct prices
		extremeHighMet = midPrice >= les.extremeConfidence
		highConfBuyMet = midPrice >= les.highConfThreshold   // 0.75+ minimum buy
		veryHighConfBuyMet = midPrice >= les.veryHighConfBuy  // 0.85+ preferred buy
		lossExitMet = midPrice <= les.minHoldPrice            // 0.70- sell to minimize loss
		minSizeForBuy := math.Min(
			maxPosSize / book.BestAskParsed,
			book.BestAskSizeParsed*0.75,
		) > 0.5
		minSizeForConservativeBuy := math.Min(
			(maxPosSize * 0.25) / book.BestAskParsed,
			book.BestAskSizeParsed*0.15,
		) > 0.5
		minSizeForStandardBuy := math.Min(
			(maxPosSize * 0.35) / book.BestAskParsed,
			book.BestAskSizeParsed*0.25,
		) > 0.5
		minSizeForLossExit := math.Min(
			(maxPosSize * 0.5) / book.BestBidParsed,
			book.BestBidSizeParsed*0.5,
		) > 0.5

		// Log all conditions
		log.Printf("[LateEntry] %s: CONDITIONS @ %ds remaining (maxPosSize: $%.2f) [%s]:", marketID, secondsRemaining, maxPosSize, outcome)
		log.Printf("  [%v] In final seconds (<%d)           | inFinalSeconds=%v", boolToCheck(inFinalSeconds), 10, inFinalSeconds)
		log.Printf("  [%v] Extreme high confidence (≥%.4f)   | price=%.4f", boolToCheck(extremeHighMet), les.extremeConfidence, midPrice)
		log.Printf("  [%v] High confidence BUY (≥%.4f)      | price=%.4f (NO buys below 0.75)", boolToCheck(highConfBuyMet), les.highConfThreshold, midPrice)
		log.Printf("  [%v] Prefer high BUY (≥%.4f)         | price=%.4f (LARGER position)", boolToCheck(veryHighConfBuyMet), les.veryHighConfBuy, midPrice)
		log.Printf("  [%v] LOSS EXIT (≤%.4f)               | price=%.4f (SELL to minimize)", boolToCheck(lossExitMet), les.minHoldPrice, midPrice)
		log.Printf("  [%v] Size OK for extreme BUY (%.1f)    | extremeSize=%.0f", boolToCheck(minSizeForBuy), 0.5, math.Min(maxPosSize/book.BestAskParsed, book.BestAskSizeParsed*0.75))
		log.Printf("  [%v] Size OK for conservative BUY (%.1f) | conservativeSize=%.0f", boolToCheck(minSizeForConservativeBuy), 0.5, math.Min((maxPosSize*0.25)/book.BestAskParsed, book.BestAskSizeParsed*0.15))
		log.Printf("  [%v] Size OK for standard BUY (%.1f)     | standardSize=%.0f", boolToCheck(minSizeForStandardBuy), 0.5, math.Min((maxPosSize*0.35)/book.BestAskParsed, book.BestAskSizeParsed*0.25))
		log.Printf("  [%v] Size OK for loss exit SELL (%.1f)    | exitSize=%.0f", boolToCheck(minSizeForLossExit), 0.5, math.Min((maxPosSize*0.5)/book.BestBidParsed, book.BestBidSizeParsed*0.5))

		// STRATEGY 1: Final seconds - aggressive trading at extreme confidence (0.98+)
		if inFinalSeconds {
			log.Printf("[LateEntry] %s (%s): FINAL SECONDS - checking for extreme confidence...", marketID, outcome)
			// Only trade at extreme certainty: 0.98+
			if extremeHighMet && minSizeForBuy {
				// HARD MINIMUM: Verify actual share price is above $0.85 before placing order
				if book.BestAskParsed < 0.85 {
					log.Printf("[LateEntry] %s (%s): ✗ BUY CANCELLED - Share price $%.4f below hard minimum $0.85", marketID, outcome, book.BestAskParsed)
					continue
				}
				
				// High confidence on outcome - BUY it
				positionSize := math.Min(
					maxPosSize / book.BestAskParsed,
					book.BestAskSizeParsed*0.75,
				)
				log.Printf("[LateEntry] %s (%s): ✓ SIGNAL - BUY (extreme high: >= %.4f), size: %.0f", marketID, outcome, les.extremeConfidence, positionSize)
				if positionSize > 0.5 {
					les.lastTradeTime = time.Now()
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
		}

		// STRATEGY 2: Final minute - HIGH CONFIDENCE ONLY (0.75+), focus on winning buys
		// Tier 1: High Confidence (0.75-0.84) - conservative position size
		// Tier 2: Prefer High (0.85+) - standard position size
		// LOSS EXIT: Sell inventory if price drops below 0.70 to minimize losses

		// HIGH CONFIDENCE BUY (0.85+): Only when outcome price is high confidence
		// Allowed from 1:30 onward if high conf is met
		if inFinalMinute && highConfBuyMet && !veryHighConfBuyMet && minSizeForConservativeBuy {
			// HARD MINIMUM: Verify actual share price is above $0.85 before placing order
			if book.BestAskParsed < 0.85 {
				log.Printf("[LateEntry] %s (%s): ✗ BUY TIER 1 CANCELLED - Share price $%.4f below hard minimum $0.85", marketID, outcome, book.BestAskParsed)
				continue
			}
			
			// 0.85-0.94 range: Conservative position size
			positionSize := math.Min(
				(maxPosSize * 0.25) / book.BestAskParsed, // Only 25% of max
				book.BestAskSizeParsed*0.15, // Take only 15% of liquidity
			)
			log.Printf("[LateEntry] %s (%s): ✓ SIGNAL - BUY TIER 1 (high conf: in [0.85-0.94]), size: %.0f", marketID, outcome, positionSize)
			if positionSize > 0.5 {
				les.lastTradeTime = time.Now()
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

		// VERY HIGH CONFIDENCE BUY (0.95+): Prefer higher confidence entries
		// Allowed from 1:30 onward if very high conf is met
		if inFinalMinute && veryHighConfBuyMet && minSizeForStandardBuy {
			// HARD MINIMUM: Verify actual share price is above $0.85 before placing order
			if book.BestAskParsed < 0.85 {
				log.Printf("[LateEntry] %s (%s): ✗ BUY TIER 2 CANCELLED - Share price $%.4f below hard minimum $0.85", marketID, outcome, book.BestAskParsed)
				continue
			}
			
			// 0.95+ range: Standard position size (more than conservative)
			positionSize := math.Min(
				(maxPosSize * 0.35) / book.BestAskParsed, // 35% of max
				book.BestAskSizeParsed*0.25, // Take 25% of liquidity
			)
			log.Printf("[LateEntry] %s (%s): ✓ SIGNAL - BUY TIER 2 (prefer high: >= 0.95), size: %.0f", marketID, outcome, positionSize)
			if positionSize > 0.5 {
				les.lastTradeTime = time.Now()
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

		// LOSS EXIT: Sell inventory if price drops below 0.70 to minimize loss
		if lossExitMet && minSizeForLossExit {
			ownedShares := les.ownedInventory[marketID]
			if ownedShares > 0 {
				// We own shares and price is below hold threshold - SELL to minimize loss
				positionSize := math.Min(
					(maxPosSize * 0.5) / book.BestBidParsed,
					book.BestBidSizeParsed*0.5,
				)
				// Cap position size to what we actually own
				if positionSize > ownedShares {
					positionSize = ownedShares
				}
				
				log.Printf("[LateEntry] %s (%s): ✓ SIGNAL - LOSS EXIT SELL (price dropped below 0.70), size: %.0f (own: %.0f)", 
					marketID, outcome, positionSize, ownedShares)
				if positionSize > 0.5 {
					les.lastTradeTime = time.Now()
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
	}

	return &TradeSignal{ShouldTrade: false}
}

// OnOrderPlaced is called after an order is executed
// This tracks inventory: BUY adds to ownedInventory, SELL subtracts from it
func (les *LateEntryStrategy) OnOrderPlaced(marketID string, side string, price float64, size float64) {
	if side == "BUY" {
		// Add to inventory when we BUY
		les.ownedInventory[marketID] += size
		log.Printf("[LateEntry] %s: Inventory updated - BUY +%.0f shares (total: %.0f)", marketID, size, les.ownedInventory[marketID])
	} else if side == "SELL" {
		// Subtract from inventory when we SELL
		les.ownedInventory[marketID] -= size
		if les.ownedInventory[marketID] < 0 {
			les.ownedInventory[marketID] = 0 // Prevent negative inventory
		}
		log.Printf("[LateEntry] %s: Inventory updated - SELL -%.0f shares (total: %.0f)", marketID, size, les.ownedInventory[marketID])
	}
}

// OnMarketWindowChange is called when a new 5-minute window begins
func (les *LateEntryStrategy) OnMarketWindowChange() {
	les.windowStartTime = time.Now()
	les.lastCheckTime = time.Now()
	les.ownedInventory = make(map[string]float64)   // Reset inventory for new window
}

// Reset clears internal state
func (les *LateEntryStrategy) Reset() {
	les.windowStartTime = time.Now()
	les.lastCheckTime = time.Now()
	les.ownedInventory = make(map[string]float64)  // Reset inventory
	les.lastTradeTime = time.Time{}                // Reset last trade time
}

// boolToCheck converts a boolean to a visual indicator (✓ or ✗)
func boolToCheck(b bool) string {
	if b {
		return "✓"
	}
	return "✗"
}
