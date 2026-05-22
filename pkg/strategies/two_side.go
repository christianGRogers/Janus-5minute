package strategies

import (
	"log"
	"math"
	"time"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// TwoSideStrategy executes a balanced two-sided entry followed by late-stage exit
// 1. At market open (first ~5 seconds), buy 1 share of each outcome near $0.50
// 2. Hold both positions until the final 60 seconds
// 3. In the final 60 seconds, identify the weaker outcome (price drops to 0.25-0.30)
// 4. SELL the losing side, HOLD the winning side until market close
// This strategy seeks to profit from the momentum shift in the final minute
type TwoSideStrategy struct {
	*BaseStrategy
	windowStartTime      time.Time
	lastCheckTime        time.Time
	lastTradeTime        time.Time
	ownedInventory       map[string]map[string]float64 // market -> (outcome -> shares)
	marketExposure       map[string]float64             // market -> total USDC spent
	currentWindow        int64                          // Current 5-minute window number
	boughtThisWindow     map[string]bool                // Track if we've already bought both sides this window
	exitThisWindow       map[string]bool                // Track if we've already exited positions this window
	entryPhaseThreshold  time.Duration                  // Time window for initial entry (first ~5 seconds)
	exitPhaseThreshold   time.Duration                  // Time until we should exit (~240 seconds, last 60 seconds)
	targetEntryPrice     float64                        // Target entry near $0.50
	entryPriceTolerance  float64                        // Allow +/- this much from target
	losingOutcomeMaxPrice float64                       // Losing outcome should be around 0.25-0.30
	sharesPerOutcome     float64                        // How many shares to buy per outcome (1 share ~$0.50 each)
	minCashPerMarket     float64                        // Minimum cash per market (we want to spend ~$1 per market)
}

// NewTwoSideStrategy creates a new two-sided strategy
func NewTwoSideStrategy(engine trading.TradingEngine) *TwoSideStrategy {
	log.Printf("Initializing TwoSideStrategy - Entry: First 5 sec at $0.50 (1 share/outcome), Exit: Last 60 sec when losing side drops to 0.25-0.30")
	strategy := &TwoSideStrategy{
		BaseStrategy:         NewBaseStrategy(engine),
		windowStartTime:      time.Now(),
		lastCheckTime:        time.Now(),
		ownedInventory:       make(map[string]map[string]float64),
		marketExposure:       make(map[string]float64),
		currentWindow:        time.Now().Unix() / 300,
		boughtThisWindow:     make(map[string]bool),
		exitThisWindow:       make(map[string]bool),
		entryPhaseThreshold:  15 * time.Second,      // Buy in first 15 seconds (extended window due to discovery delay)
		exitPhaseThreshold:   240 * time.Second,     // Exit when < 60 seconds remain (300 - 60 = 240)
		targetEntryPrice:     0.50,                  // Target $0.50 per share
		entryPriceTolerance:  0.15,                  // Allow 0.35-0.65 range (wider tolerance for market volatility)
		losingOutcomeMaxPrice: 0.30,                 // Losing side when price drops to this level
		sharesPerOutcome:     1.0,                   // 1 share per outcome (costs ~$0.50 each)
		minCashPerMarket:     1.0,                   // Minimum ~$1 per market
	}
	strategy.Config.RiskTolerance = 0.05 // Conservative: only ~5% of balance per market
	strategy.Config.MaxPositionSize = 0   // Disable fixed max, use dynamic sizing
	return strategy
}

// Name returns the strategy name
func (ts *TwoSideStrategy) Name() string {
	return "TwoSide"
}

// EvaluateV2 analyzes market data and returns trading signals
// Phase 1 (Entry): First 5 seconds - buy 1 share of each outcome near $0.50
// Phase 2 (Hold): 5-240 seconds - do nothing, hold positions
// Phase 3 (Exit): Last 60 seconds - sell the weaker outcome when it drops to 0.25-0.30
func (ts *TwoSideStrategy) EvaluateV2(markets map[string]*polymarket.MarketBook) *TradeSignal {
	now := time.Now()

	// Calculate the ACTUAL 5-minute market window based on current time
	// Markets are in 300-second (5-minute) windows: 0:00-4:59, 5:00-9:59, etc.
	currentWindowNumber := now.Unix() / 300       // Which 5-minute window are we in?
	windowStartUnix := currentWindowNumber * 300  // Timestamp of this window's start
	windowStartTime := time.Unix(windowStartUnix, 0)

	// Calculate time remaining in the 5-minute window
	timeInWindow := now.Sub(windowStartTime)
	secondsIntoWindow := int(timeInWindow.Seconds())
	secondsRemaining := 300 - secondsIntoWindow // 5 minutes = 300 seconds
	timeRemaining := time.Duration(secondsRemaining) * time.Second

	// Detect new window and reset state
	if ts.currentWindow != currentWindowNumber {
		ts.OnMarketWindowChange()
		ts.currentWindow = currentWindowNumber
		log.Printf("[TwoSide] New market window started - window #%d", currentWindowNumber)
	}

	inEntryPhase := timeInWindow <= ts.entryPhaseThreshold           // First 5 seconds
	inExitPhase := timeRemaining <= (60 * time.Second)              // Last 60 seconds
	inHoldPhase := !inEntryPhase && !inExitPhase                    // Middle period - just hold

	log.Printf("[TwoSide] EVALUATE - Window: %ds into 300s (%d seconds remaining) - Entry: %v, Hold: %v, Exit: %v",
		secondsIntoWindow, secondsRemaining, inEntryPhase, inHoldPhase, inExitPhase)

	// Iterate through each market in the book
	// Markets come with keys like "btc-updown-5m-1779480300-UP" or "btc-updown-5m-1779480300-DOWN"
	for cacheKey, book := range markets {
		if book == nil {
			continue
		}

		// Extract outcome from cache key (same pattern as late_entry)
		var outcome string
		var baseMarketID string

		if len(cacheKey) >= 3 && cacheKey[len(cacheKey)-2:] == "UP" {
			outcome = "UP"
			baseMarketID = cacheKey[:len(cacheKey)-3]
		} else if len(cacheKey) >= 4 && cacheKey[len(cacheKey)-4:] == "DOWN" {
			outcome = "DOWN"
			baseMarketID = cacheKey[:len(cacheKey)-5]
		} else {
			continue
		}

		// PHASE 1: ENTRY - Buy 1 share of each outcome near $0.50 in first 5 seconds
		if inEntryPhase && !ts.boughtThisWindow[baseMarketID] {
			log.Printf("[TwoSide] %s (%s): ENTRY PHASE - Evaluating for two-sided entry", baseMarketID, outcome)

			// Initialize inventory for this market if not already done
			if ts.ownedInventory[baseMarketID] == nil {
				ts.ownedInventory[baseMarketID] = make(map[string]float64)
			}

			// For binary markets, the complementary outcome price = 1.0 - this outcome's price
			thisOutcomePrice := book.BestAskParsed
			complementOutcomePrice := 1.0 - thisOutcomePrice

			// Determine if both outcomes are near $0.50
			thisNear50 := math.Abs(thisOutcomePrice-ts.targetEntryPrice) <= ts.entryPriceTolerance
			complementNear50 := math.Abs(complementOutcomePrice-ts.targetEntryPrice) <= ts.entryPriceTolerance

			if !thisNear50 || !complementNear50 {
				log.Printf("[TwoSide] %s (%s): ✗ ENTRY SKIPPED - Prices not near $0.50 (%s: $%.4f, other: $%.4f)", 
					baseMarketID, outcome, outcome, thisOutcomePrice, complementOutcomePrice)
				continue
			}

			// Calculate minimum shares to meet $1 order minimum
			// If price is $0.39, we need at least $1 / $0.39 = 2.56 shares (round up to 3)
			minSharesForMinOrder := math.Ceil(ts.minCashPerMarket / thisOutcomePrice)
			sharesToBuy := math.Max(ts.sharesPerOutcome, minSharesForMinOrder)

			// Check available liquidity on both sides
			hasLiquidityThis := book.BestAskSizeParsed >= sharesToBuy
			hasLiquidityComplement := book.BestBidSizeParsed >= sharesToBuy

			if !hasLiquidityThis || !hasLiquidityComplement {
				log.Printf("[TwoSide] %s (%s): ✗ ENTRY SKIPPED - Insufficient liquidity (%s ask: %.0f, bid: %.0f, need: %.0f)", 
					baseMarketID, outcome, outcome, book.BestAskSizeParsed, book.BestBidSizeParsed, sharesToBuy)
				continue
			}

			// First, BUY this outcome
			ts.boughtThisWindow[baseMarketID] = true // Mark that we've initiated trading for this market
			ts.lastTradeTime = now
			ts.ownedInventory[baseMarketID][outcome] = sharesToBuy
			ts.marketExposure[baseMarketID] += sharesToBuy * thisOutcomePrice

			log.Printf("[TwoSide] %s (%s): ✓ SIGNAL - BUY %s (first leg), %.1f shares at $%.4f (cost: $%.2f, min order: $%.2f)", 
				baseMarketID, outcome, outcome, sharesToBuy, thisOutcomePrice, sharesToBuy*thisOutcomePrice, ts.minCashPerMarket)

			return &TradeSignal{
				ShouldTrade:        true,
				MarketID:           baseMarketID, // Return base market ID, outcome is specified separately
				Side:               "BUY",
				Price:              thisOutcomePrice,
				Size:               ts.sharesPerOutcome,
				AvailableLiquidity: book.BestAskSizeParsed,
				Outcome:            outcome,
			}
		}

		// After the first BUY signal, we need to detect the second buy (complementary outcome)
		// This happens when we see the complementary outcome key in the next evaluation call
		complementOutcome := "DOWN"
		if outcome == "DOWN" {
			complementOutcome = "UP"
		}

		if inEntryPhase && ts.boughtThisWindow[baseMarketID] && outcome == complementOutcome && ts.ownedInventory[baseMarketID][complementOutcome] == 0 {
			log.Printf("[TwoSide] %s (%s): ENTRY PHASE - Second leg (%s) not yet purchased, buying now", baseMarketID, outcome, outcome)

			if ts.ownedInventory[baseMarketID] == nil {
				ts.ownedInventory[baseMarketID] = make(map[string]float64)
			}

			thisOutcomePrice := book.BestAskParsed

			// Check liquidity for this outcome
			hasLiquidityThis := book.BestAskSizeParsed >= ts.sharesPerOutcome
			if !hasLiquidityThis {
				log.Printf("[TwoSide] %s (%s): ✗ BUY SKIPPED - Insufficient liquidity (%.0f shares available)", 
					baseMarketID, outcome, book.BestAskSizeParsed)
				continue
			}

			// BUY the complementary outcome
			ts.ownedInventory[baseMarketID][outcome] = ts.sharesPerOutcome
			ts.marketExposure[baseMarketID] += ts.sharesPerOutcome * thisOutcomePrice
			ts.lastTradeTime = now

			log.Printf("[TwoSide] %s (%s): ✓ SIGNAL - BUY %s (second leg), %.1f shares at $%.4f (cost: $%.2f, total invested: $%.2f)", 
				baseMarketID, outcome, outcome, ts.sharesPerOutcome, thisOutcomePrice, ts.sharesPerOutcome*thisOutcomePrice, ts.marketExposure[baseMarketID])

			return &TradeSignal{
				ShouldTrade:        true,
				MarketID:           baseMarketID, // Return base market ID, outcome is specified separately
				Side:               "BUY",
				Price:              thisOutcomePrice,
				Size:               ts.sharesPerOutcome,
				AvailableLiquidity: book.BestAskSizeParsed,
				Outcome:            outcome,
			}
		}

		// PHASE 3: EXIT - Sell the weaker side in final 60 seconds when it drops to 0.25-0.30
		if inExitPhase && !ts.exitThisWindow[baseMarketID] && ts.boughtThisWindow[baseMarketID] {
			log.Printf("[TwoSide] %s (%s): EXIT PHASE - Evaluating for exit (timeRemaining: %ds)", baseMarketID, outcome, secondsRemaining)

			if ts.ownedInventory[baseMarketID] == nil {
				continue
			}

			sharesThisOutcome := ts.ownedInventory[baseMarketID][outcome]
			sharesComplementOutcome := ts.ownedInventory[baseMarketID][complementOutcome]

			// Only exit if we own both sides
			if sharesThisOutcome == 0 || sharesComplementOutcome == 0 {
				log.Printf("[TwoSide] %s (%s): ✗ EXIT SKIPPED - Don't own both sides (%s: %.1f, %s: %.1f)", 
					baseMarketID, outcome, outcome, sharesThisOutcome, complementOutcome, sharesComplementOutcome)
				continue
			}

			thisOutcomePrice := book.BestAskParsed
			complementOutcomePrice := 1.0 - thisOutcomePrice

			log.Printf("[TwoSide] %s: Prices - %s: $%.4f, %s: $%.4f", baseMarketID, outcome, thisOutcomePrice, complementOutcome, complementOutcomePrice)

			// Determine which side is losing
			// Losing side is when price drops significantly (to around 0.25-0.30)
			thisIsLosing := thisOutcomePrice <= ts.losingOutcomeMaxPrice
			complementIsLosing := complementOutcomePrice <= ts.losingOutcomeMaxPrice

			if thisIsLosing && sharesComplementOutcome > 0 {
				// This outcome is losing, SELL it
				ts.exitThisWindow[baseMarketID] = true
				ts.ownedInventory[baseMarketID][outcome] = 0
				ts.lastTradeTime = now

				log.Printf("[TwoSide] %s (%s): ✓ SIGNAL - SELL %s (losing side at $%.4f), %.1f shares (buy price was ~$0.50)", 
					baseMarketID, outcome, outcome, thisOutcomePrice, sharesThisOutcome)

				return &TradeSignal{
					ShouldTrade:        true,
					MarketID:           baseMarketID, // Return base market ID, outcome is specified separately
					Side:               "SELL",
					Price:              thisOutcomePrice,
					Size:               sharesThisOutcome,
					AvailableLiquidity: book.BestBidSizeParsed,
					Outcome:            outcome,
				}

			} else if complementIsLosing && sharesThisOutcome > 0 {
				// Complement outcome is losing, but we can't sell it from this market key
				// We'll let the next iteration handle it when we see the complementary outcome key
				log.Printf("[TwoSide] %s (%s): Complement outcome is losing, waiting for %s key to sell it", 
					baseMarketID, outcome, complementOutcome)

			} else {
				log.Printf("[TwoSide] %s (%s): ✗ EXIT NOT TRIGGERED - Prices haven't diverged enough (%s: $%.4f, %s: $%.4f, threshold: $%.2f)", 
					baseMarketID, outcome, outcome, thisOutcomePrice, complementOutcome, complementOutcomePrice, ts.losingOutcomeMaxPrice)
			}
		}

		// PHASE 2: HOLD - Do nothing, just hold positions
		if inHoldPhase {
			log.Printf("[TwoSide] %s (%s): HOLD PHASE - Maintaining positions", baseMarketID, outcome)
		}
	}

	// No trade signal this evaluation
	return &TradeSignal{
		ShouldTrade: false,
	}
}

// OnOrderPlaced is called after a trade is executed
func (ts *TwoSideStrategy) OnOrderPlaced(marketID string, side string, price float64, size float64) {
	// This is called by the trading engine after a successful order
	// We use OnOrderPlaced to sync our inventory records
	// (Our EvaluateV2 updates inventory directly, so this is informational)
	if side == "BUY" {
		log.Printf("[TwoSide] Order executed: BUY %s at $%.4f, size: %.0f", marketID, price, size)
	} else {
		log.Printf("[TwoSide] Order executed: SELL %s at $%.4f, size: %.0f", marketID, price, size)
	}
}

// OnMarketWindowChange is called when a new 5-minute window begins
func (ts *TwoSideStrategy) OnMarketWindowChange() {
	ts.windowStartTime = time.Now()
	ts.lastCheckTime = time.Now()
	ts.ownedInventory = make(map[string]map[string]float64) // Reset inventory for new window
	ts.marketExposure = make(map[string]float64)             // Reset market exposure for new window
	ts.boughtThisWindow = make(map[string]bool)              // Reset bought tracking
	ts.exitThisWindow = make(map[string]bool)                // Reset exit tracking
	log.Printf("[TwoSide] Market window changed - inventory and state reset")
}

// Reset clears internal state
func (ts *TwoSideStrategy) Reset() {
	ts.windowStartTime = time.Now()
	ts.lastCheckTime = time.Now()
	ts.ownedInventory = make(map[string]map[string]float64)
	ts.marketExposure = make(map[string]float64)
	ts.boughtThisWindow = make(map[string]bool)
	ts.exitThisWindow = make(map[string]bool)
	ts.lastTradeTime = time.Time{}
	ts.currentWindow = time.Now().Unix() / 300
	log.Printf("[TwoSide] Strategy state reset")
}
