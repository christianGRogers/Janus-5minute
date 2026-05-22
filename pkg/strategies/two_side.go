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
		entryPhaseThreshold:  5 * time.Second,       // Buy in first 5 seconds
		exitPhaseThreshold:   240 * time.Second,     // Exit when < 60 seconds remain (300 - 60 = 240)
		targetEntryPrice:     0.50,                  // Target $0.50 per share
		entryPriceTolerance:  0.10,                  // Allow 0.40-0.60 range
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
	timeRemaining := (300 * time.Second) - timeInWindow

	// Detect new window and reset state
	if ts.currentWindow != currentWindowNumber {
		ts.OnMarketWindowChange()
		ts.currentWindow = currentWindowNumber
		log.Printf("[TwoSide] New market window started - window #%d", currentWindowNumber)
	}

	inEntryPhase := timeInWindow <= ts.entryPhaseThreshold           // First 5 seconds
	inExitPhase := timeRemaining <= (60 * time.Second)              // Last 60 seconds
	inHoldPhase := !inEntryPhase && !inExitPhase                    // Middle period - just hold

	log.Printf("[TwoSide] Time in window: %.1fs, Remaining: %.1fs - Entry: %v, Hold: %v, Exit: %v",
		timeInWindow.Seconds(), timeRemaining.Seconds(), inEntryPhase, inHoldPhase, inExitPhase)

	// Iterate through each market in the book
	for marketID, book := range markets {
		if book == nil {
			continue
		}

		// PHASE 1: ENTRY - Buy 1 share of each outcome near $0.50 in first 5 seconds
		if inEntryPhase && !ts.boughtThisWindow[marketID] {
			log.Printf("[TwoSide] %s: ENTRY PHASE - Evaluating for two-sided entry", marketID)

			// Initialize inventory for this market if not already done
			if ts.ownedInventory[marketID] == nil {
				ts.ownedInventory[marketID] = make(map[string]float64)
			}

			// For binary markets, we need to identify the two outcomes
			// In Polymarket, we typically look at the best bid/ask to infer outcomes
			// Outcome 1: Higher priced (typically YES), Outcome 2: Lower priced (typically NO)
			upPrice := book.BestAskParsed
			downPrice := 1.0 - upPrice // For binary market, outcomes are complementary

			// Check if prices are near $0.50 (within tolerance)
			upNear50 := math.Abs(upPrice-ts.targetEntryPrice) <= ts.entryPriceTolerance
			downNear50 := math.Abs(downPrice-ts.targetEntryPrice) <= ts.entryPriceTolerance

			if !upNear50 || !downNear50 {
				log.Printf("[TwoSide] %s: ✗ ENTRY SKIPPED - Prices not near $0.50 (UP: $%.4f, DOWN: $%.4f)", 
					marketID, upPrice, downPrice)
				continue
			}

			// Check available liquidity on both sides
			hasLiquidityUp := book.BestAskSizeParsed >= ts.sharesPerOutcome
			hasLiquidityDown := book.BestBidSizeParsed >= ts.sharesPerOutcome

			if !hasLiquidityUp || !hasLiquidityDown {
				log.Printf("[TwoSide] %s: ✗ ENTRY SKIPPED - Insufficient liquidity (UP liquidity: %.0f, DOWN liquidity: %.0f)", 
					marketID, book.BestAskSizeParsed, book.BestBidSizeParsed)
				continue
			}

			// First, BUY the UP side (higher priced outcome)
			// This is the first signal, so return immediately
			ts.boughtThisWindow[marketID] = true // Mark that we've initiated trading for this market
			ts.lastTradeTime = now
			ts.ownedInventory[marketID]["UP"] = ts.sharesPerOutcome
			ts.marketExposure[marketID] += ts.sharesPerOutcome * upPrice

			log.Printf("[TwoSide] %s: ✓ SIGNAL - BUY UP (outcome 1), %.1f shares at $%.4f (cost: $%.2f)", 
				marketID, ts.sharesPerOutcome, upPrice, ts.sharesPerOutcome*upPrice)

			return &TradeSignal{
				ShouldTrade:        true,
				MarketID:           marketID,
				Side:               "BUY",
				Price:              upPrice,
				Size:               ts.sharesPerOutcome,
				AvailableLiquidity: book.BestAskSizeParsed,
				Outcome:            "UP",
			}
		}

		// After the first BUY signal, we need to detect the second buy (DOWN side)
		// This happens on the next evaluation call in the entry phase
		if inEntryPhase && ts.boughtThisWindow[marketID] && ts.ownedInventory[marketID]["DOWN"] == 0 {
			log.Printf("[TwoSide] %s: ENTRY PHASE - Second leg (DOWN) not yet purchased, buying now", marketID)

			if ts.ownedInventory[marketID] == nil {
				ts.ownedInventory[marketID] = make(map[string]float64)
			}

			upPrice := book.BestAskParsed
			downPrice := 1.0 - upPrice

			// Check liquidity for DOWN side
			hasLiquidityDown := book.BestBidSizeParsed >= ts.sharesPerOutcome
			if !hasLiquidityDown {
				log.Printf("[TwoSide] %s: ✗ DOWN BUY SKIPPED - Insufficient liquidity (%.0f shares available)", 
					marketID, book.BestBidSizeParsed)
				continue
			}

			// BUY the DOWN side
			ts.ownedInventory[marketID]["DOWN"] = ts.sharesPerOutcome
			ts.marketExposure[marketID] += ts.sharesPerOutcome * downPrice
			ts.lastTradeTime = now

			log.Printf("[TwoSide] %s: ✓ SIGNAL - BUY DOWN (outcome 2), %.1f shares at $%.4f (cost: $%.2f, total invested: $%.2f)", 
				marketID, ts.sharesPerOutcome, downPrice, ts.sharesPerOutcome*downPrice, ts.marketExposure[marketID])

			return &TradeSignal{
				ShouldTrade:        true,
				MarketID:           marketID,
				Side:               "BUY",
				Price:              downPrice,
				Size:               ts.sharesPerOutcome,
				AvailableLiquidity: book.BestBidSizeParsed,
				Outcome:            "DOWN",
			}
		}

		// PHASE 3: EXIT - Sell the weaker side in final 60 seconds when it drops to 0.25-0.30
		if inExitPhase && !ts.exitThisWindow[marketID] && ts.boughtThisWindow[marketID] {
			log.Printf("[TwoSide] %s: EXIT PHASE - Evaluating for exit (timeRemaining: %.1fs)", marketID, timeRemaining.Seconds())

			if ts.ownedInventory[marketID] == nil {
				continue
			}

			upShares := ts.ownedInventory[marketID]["UP"]
			downShares := ts.ownedInventory[marketID]["DOWN"]

			// Only exit if we own both sides
			if upShares == 0 || downShares == 0 {
				log.Printf("[TwoSide] %s: ✗ EXIT SKIPPED - Don't own both sides (UP: %.1f, DOWN: %.1f)", 
					marketID, upShares, downShares)
				continue
			}

			upPrice := book.BestAskParsed
			downPrice := 1.0 - upPrice

			log.Printf("[TwoSide] %s: Prices - UP: $%.4f, DOWN: $%.4f", marketID, upPrice, downPrice)

			// Determine which side is losing
			// Losing side is when price drops significantly (to around 0.25-0.30)
			upIsLosing := upPrice <= ts.losingOutcomeMaxPrice
			downIsLosing := downPrice <= ts.losingOutcomeMaxPrice

			if upIsLosing && downShares > 0 {
				// DOWN is winning, SELL UP
				ts.exitThisWindow[marketID] = true
				ts.ownedInventory[marketID]["UP"] = 0
				ts.lastTradeTime = now

				log.Printf("[TwoSide] %s: ✓ SIGNAL - SELL UP (losing side at $%.4f), %.1f shares (buy price was ~$0.50)", 
					marketID, upPrice, upShares)

				return &TradeSignal{
					ShouldTrade:        true,
					MarketID:           marketID,
					Side:               "SELL",
					Price:              upPrice,
					Size:               upShares,
					AvailableLiquidity: book.BestBidSizeParsed,
					Outcome:            "UP",
				}

			} else if downIsLosing && upShares > 0 {
				// UP is winning, SELL DOWN
				ts.exitThisWindow[marketID] = true
				ts.ownedInventory[marketID]["DOWN"] = 0
				ts.lastTradeTime = now

				log.Printf("[TwoSide] %s: ✓ SIGNAL - SELL DOWN (losing side at $%.4f), %.1f shares (buy price was ~$0.50)", 
					marketID, downPrice, downShares)

				return &TradeSignal{
					ShouldTrade:        true,
					MarketID:           marketID,
					Side:               "SELL",
					Price:              downPrice,
					Size:               downShares,
					AvailableLiquidity: book.BestBidSizeParsed,
					Outcome:            "DOWN",
				}

			} else {
				log.Printf("[TwoSide] %s: ✗ EXIT NOT TRIGGERED - Prices haven't diverged enough (UP: $%.4f, DOWN: $%.4f, threshold: $%.2f)", 
					marketID, upPrice, downPrice, ts.losingOutcomeMaxPrice)
			}
		}

		// PHASE 2: HOLD - Do nothing, just hold positions
		if inHoldPhase {
			log.Printf("[TwoSide] %s: HOLD PHASE - Maintaining positions", marketID)
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
