package strategies

import (
	"log"
	"math"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"time"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
	"janus-bot/pkg/analytics"
	"janus-bot/config"
)

// LateEntryStrategy prioritizes small safe wins towards the end of a 5-minute market window
// The strategy uses a two-tier system to avoid the "coin flip zone" (0.50-0.75):
// 1. Waits until less than 1 minute remains
// 2. AVOIDS medium confidence (0.50-0.75) - these cause 100% unmatched losses
// 3. HIGH confidence tier (0.80+): Small conservative buys when confident UP will win
// 4. EXTREME confidence tier (0.98+): Aggressive bets in final seconds only
// 5. CRITICAL: Tracks inventory - only allows SELL when shares are actually owned
// 6. RISK MANAGEMENT: Per-market risk cap of 30% prevents chain buy concentration
// 7. LOSS COOLDOWN: Before every trade, queries get_loss.py for recent losses.
//    Each loss applies a linear reduction: multiplier = 1 / (1 + lossCount).
//    e.g. 1 loss = 0.5x, 2 losses = 0.33x, 3 losses = 0.25x
//    A background ticker also refreshes the dashboard every 30s independently of trades.
type LateEntryStrategy struct {
	*BaseStrategy
	windowStartTime     time.Time
	lastCheckTime       time.Time
	lastTradeTime       time.Time
	currentMarketsSlugs map[string]bool
	positionsThisWindow map[string]bool
	ownedInventory      map[string]float64
	marketExposure      map[string]float64
	maxMarketExposure   float64
	highConfThreshold   float64
	veryHighConfBuy     float64
	extremeConfidence   float64
	minHoldPrice        float64
	lossTracker         *trading.LossTracker
	dashboard           *analytics.Dashboard
	lossScriptPath      string        // Path to get_loss.py
	proxyAddress        string        // PROXY_ADDRESS env var value
	lossCheckTicker     *time.Ticker  // Background ticker for dashboard loss display
}

// NewLateEntryStrategy creates a new late entry strategy
func NewLateEntryStrategy(engine trading.TradingEngine) *LateEntryStrategy {
	log.Printf("Initializing LateEntryStrategy - BUY HIGH MODE: MinBuy=0.75+, PreferHigh=0.85+, ExtremeConf=0.98+, LossExit=0.70-, PER-MARKET CAP=30%%, LOSS COOLDOWN: linear scale via get_loss.py")

	lossScriptPath := os.Getenv("LOSS_SCRIPT_PATH")
	if lossScriptPath == "" {
		lossScriptPath = "tools/get_loss.py"
	}

	proxyAddress := os.Getenv("PROXY_ADDRESS")
	if proxyAddress == "" {
		log.Printf("[LateEntry] WARNING: PROXY_ADDRESS env var not set - loss checking will be skipped")
	}

	strategy := &LateEntryStrategy{
		BaseStrategy:        NewBaseStrategy(engine),
		windowStartTime:     time.Now(),
		lastCheckTime:       time.Now(),
		currentMarketsSlugs: make(map[string]bool),
		positionsThisWindow: make(map[string]bool),
		ownedInventory:      make(map[string]float64),
		marketExposure:      make(map[string]float64),
		maxMarketExposure:   0.35,
		highConfThreshold:   0.85,
		veryHighConfBuy:     0.95,
		extremeConfidence:   0.98,
		minHoldPrice:        0.70,
		lossTracker:         nil,
		dashboard:           analytics.NewDashboard(engine.GetBalance()),
		lossScriptPath:      lossScriptPath,
		proxyAddress:        proxyAddress,
	}
	strategy.Config.RiskTolerance = 0.40
	strategy.Config.MaxPositionSize = 0

	// Start background loss checker so dashboard shows cooldown state
	// even when no trade has fired yet
	go strategy.runLossCheckLoop()

	return strategy
}

// runLossCheckLoop runs on a 30-second ticker and keeps the dashboard cooldown
// display current regardless of whether any trades are executing.
func (les *LateEntryStrategy) runLossCheckLoop() {
	ticker := time.NewTicker(30 * time.Second)
	les.lossCheckTicker = ticker

	// Run immediately on start so dashboard is populated right away
	les.refreshLossCooldownDisplay()

	for range ticker.C {
		les.refreshLossCooldownDisplay()
	}
}

// refreshLossCooldownDisplay queries get_loss.py and pushes the result to the
// dashboard. Sets the cooldown display if losses > 0, clears it if losses == 0.
func (les *LateEntryStrategy) refreshLossCooldownDisplay() {
	lossCount := les.queryLossCount()
	multiplier := les.lossCountToMultiplier(lossCount)
	if lossCount > 0 {
		les.dashboard.SetActiveCooldown("recent-losses", multiplier, 3*time.Hour)
		log.Printf("[LateEntry] Loss cooldown active: %d losses in last 3h → %.2fx position size", lossCount, multiplier)
	} else {
		les.dashboard.SetActiveCooldown("recent-losses", 1.0, 0) // 0 duration clears it
	}
}

// queryLossCount shells out to get_loss.py and returns the number of recent losses.
// Returns 0 and logs a warning if the script fails or PROXY_ADDRESS is unset.
func (les *LateEntryStrategy) queryLossCount() int {
	if les.proxyAddress == "" {
		return 0
	}

	cmd := exec.Command("python3", les.lossScriptPath)
	cmd.Env = append(os.Environ(), "PROXY_ADDRESS="+les.proxyAddress)

	out, err := cmd.Output()
	if err != nil {
		log.Printf("[LateEntry] WARNING: get_loss.py failed: %v", err)
		return 0
	}

	countStr := strings.TrimSpace(string(out))
	count, err := strconv.Atoi(countStr)
	if err != nil {
		log.Printf("[LateEntry] WARNING: get_loss.py returned non-integer output: %q", countStr)
		return 0
	}

	return count
}

// lossCountToMultiplier converts a loss count to a linear position size multiplier.
// Formula: 1 / (1 + lossCount)
//   0 losses → 1.00x (no reduction)
//   1 loss   → 0.50x
//   2 losses → 0.33x
//   3 losses → 0.25x
//   4 losses → 0.20x
func (les *LateEntryStrategy) lossCountToMultiplier(lossCount int) float64 {
	if lossCount <= 0 {
		return 1.0
	}
	return 1.0 / float64(1+lossCount)
}

// applyLossCooldown queries get_loss.py, refreshes the dashboard display,
// and returns the position size multiplier. Call immediately before any trade signal.
func (les *LateEntryStrategy) applyLossCooldown() float64 {
	lossCount := les.queryLossCount()
	multiplier := les.lossCountToMultiplier(lossCount)
	les.refreshLossCooldownDisplay()
	return multiplier
}

// SetLossTracker sets the loss tracker for this strategy
func (les *LateEntryStrategy) SetLossTracker(tracker *trading.LossTracker) {
	les.lossTracker = tracker
	log.Printf("[LateEntry] Loss tracker configured")
}

// SetDashboard sets the dashboard for displaying trading status
func (les *LateEntryStrategy) SetDashboard(dashboard *analytics.Dashboard) {
	les.dashboard = dashboard
}

// UpdateDashboardRiskState updates the dashboard with current risk score and multipliers
func (les *LateEntryStrategy) UpdateDashboardRiskState() {
	if les.dashboard == nil {
		return
	}

	now := time.Now()
	hour := now.Hour()
	minute := now.Minute()

	riskScore := config.GetRiskScoreForFiveMinuteInterval(hour, minute)
	safetyLevel := config.GetSafetyLevel(riskScore)
	hourMultiplier := 0.3 + (riskScore * 0.7)

	lossMultiplier := 1.0
	if les.lossTracker != nil {
		lossMultiplier = les.lossTracker.GetRiskMultiplier("")
	}

	combinedMultiplier := hourMultiplier * lossMultiplier
	les.dashboard.SetRiskState(riskScore, safetyLevel, hourMultiplier, lossMultiplier, combinedMultiplier)
}

// getRiskAdjustmentMultiplier returns a position size multiplier based on the
// current 5-minute interval risk score. The loss cooldown is handled separately
// via applyLossCooldown() at trade execution time.
func (les *LateEntryStrategy) getRiskAdjustmentMultiplier(marketTitle string) float64 {
	now := time.Now()
	hour := now.Hour()
	minute := now.Minute()

	riskScore := config.GetRiskScoreForFiveMinuteInterval(hour, minute)
	hourMultiplier := 0.3 + (riskScore * 0.7)

	lossMultiplier := 1.0
	if les.lossTracker != nil {
		lossMultiplier = les.lossTracker.GetRiskMultiplier(marketTitle)
	}

	combinedMultiplier := hourMultiplier * lossMultiplier

	safetyLevel := config.GetSafetyLevel(riskScore)
	if les.dashboard != nil {
		les.dashboard.SetRiskState(riskScore, safetyLevel, hourMultiplier, lossMultiplier, combinedMultiplier)
	}

	return combinedMultiplier
}

// Name returns the strategy name
func (les *LateEntryStrategy) Name() string {
	return "LateEntry"
}

// calculateSafePositionSize calculates position size respecting both per-trade and per-market caps
func (les *LateEntryStrategy) calculateSafePositionSize(marketID string, marketTitle string, percentOfMax float64) (float64, float64, float64, bool) {
	if les.Engine == nil {
		return 0, 0, 0, false
	}

	balance := les.Engine.GetBalance()
	riskMultiplier := les.getRiskAdjustmentMultiplier(marketTitle)

	maxPerTradeSize := balance * les.Config.RiskTolerance * percentOfMax * riskMultiplier

	currentMarketExposure := les.marketExposure[marketID]
	maxMarketAllowance := balance * les.maxMarketExposure
	remainingMarketCapacity := maxMarketAllowance - currentMarketExposure

	recommendedSize := math.Min(maxPerTradeSize, remainingMarketCapacity)
	isWithinCap := (currentMarketExposure + recommendedSize) <= maxMarketAllowance

	return maxPerTradeSize, remainingMarketCapacity, recommendedSize, isWithinCap
}

// EvaluateV2 analyzes market data and returns a complete trading signal.
// Immediately before returning any BUY signal, queries get_loss.py and
// scales the position size down linearly based on the number of recent losses.
// SELL (loss exit) signals are never scaled down.
func (les *LateEntryStrategy) EvaluateV2(markets map[string]*polymarket.MarketBook) *TradeSignal {

	now := time.Now()
	currentWindowNumber := now.Unix() / 300
	windowStartUnix := currentWindowNumber * 300
	windowStartTime := time.Unix(windowStartUnix, 0)

	timeSinceWindowStart := now.Sub(windowStartTime)
	secondsIntoWindow := int(timeSinceWindowStart.Seconds())
	secondsRemaining := 300 - secondsIntoWindow

	les.lastCheckTime = time.Now()

	if secondsRemaining >= 30 {
		return &TradeSignal{ShouldTrade: false}
	}

	allowTrading := secondsRemaining < 90
	if !allowTrading {
		return &TradeSignal{ShouldTrade: false}
	}

	for cacheKey, book := range markets {
		if book == nil {
			continue
		}

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

		les.currentMarketsSlugs[marketID] = true

		if book.BestBidParsed == 0 && book.BestAskParsed == 0 {
			continue
		}

		if book.LiquidityParsed < les.Config.MinLiquidityUSDC {
			continue
		}

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

		if book.BestBidParsed > 0 && book.BestAskParsed > 0 {
			if spreadPercent < les.Config.MinSpread || spreadPercent > les.Config.MaxSpread {
				continue
			}
		}

		inFinalSeconds := secondsRemaining < 10
		inFinalMinute := secondsRemaining < 30

		maxPosSize := les.GetDynamicPositionSize()

		extremeHighMet := midPrice >= les.extremeConfidence
		highConfBuyMet := midPrice >= les.highConfThreshold
		veryHighConfBuyMet := midPrice >= les.veryHighConfBuy
		lossExitMet := midPrice <= les.minHoldPrice

		minSizeForBuy := false
		minSizeForConservativeBuy := false
		minSizeForStandardBuy := false
		minSizeForLossExit := false

		if book.BestAskParsed > 0 {
			minSizeForBuy = math.Min(
				maxPosSize/book.BestAskParsed,
				book.BestAskSizeParsed*0.75,
			) > 0.5
			minSizeForConservativeBuy = math.Min(
				(maxPosSize*0.25)/book.BestAskParsed,
				book.BestAskSizeParsed*0.15,
			) > 0.5
			minSizeForStandardBuy = math.Min(
				(maxPosSize*0.35)/book.BestAskParsed,
				book.BestAskSizeParsed*0.25,
			) > 0.5
		}

		if book.BestBidParsed > 0 {
			minSizeForLossExit = math.Min(
				(maxPosSize*0.5)/book.BestBidParsed,
				book.BestBidSizeParsed*0.5,
			) > 0.5
		}

		// STRATEGY 1: Final seconds — aggressive trading at extreme confidence (0.98+)
		if inFinalSeconds && extremeHighMet && minSizeForBuy {
			if book.BestAskParsed < 0.85 {
				continue
			}

			_, _, recommendedSize, withinCap := les.calculateSafePositionSize(marketID, marketID, 1.0)
			if !withinCap {
				continue
			}

			positionSize := math.Min(
				math.Min(maxPosSize/book.BestAskParsed, book.BestAskSizeParsed*0.75),
				recommendedSize/book.BestAskParsed,
			)

			if positionSize > 0.5 {
				lossMultiplier := les.applyLossCooldown()
				positionSize *= lossMultiplier

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

		// STRATEGY 2: High confidence buy (0.85–0.94) — conservative position size
		if inFinalMinute && highConfBuyMet && !veryHighConfBuyMet && minSizeForConservativeBuy {
			if book.BestAskParsed < 0.85 {
				continue
			}

			_, _, recommendedSize, withinCap := les.calculateSafePositionSize(marketID, marketID, 0.25)
			if !withinCap {
				continue
			}

			positionSize := math.Min(
				math.Min((maxPosSize*0.25)/book.BestAskParsed, book.BestAskSizeParsed*0.15),
				recommendedSize/book.BestAskParsed,
			)

			if positionSize > 0.5 {
				lossMultiplier := les.applyLossCooldown()
				positionSize *= lossMultiplier

				if positionSize > 0.5 {
					les.lastTradeTime = time.Now()
					les.dashboard.RecordTrade("BUY", marketID, book.BestAskParsed, positionSize)
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

		// STRATEGY 3: Very high confidence buy (0.95+) — standard position size
		if inFinalMinute && veryHighConfBuyMet && minSizeForStandardBuy {
			if book.BestAskParsed < 0.85 {
				continue
			}

			_, _, recommendedSize, withinCap := les.calculateSafePositionSize(marketID, marketID, 0.35)
			if !withinCap {
				continue
			}

			positionSize := math.Min(
				math.Min((maxPosSize*0.35)/book.BestAskParsed, book.BestAskSizeParsed*0.25),
				recommendedSize/book.BestAskParsed,
			)

			if positionSize > 0.5 {
				lossMultiplier := les.applyLossCooldown()
				positionSize *= lossMultiplier

				if positionSize > 0.5 {
					les.lastTradeTime = time.Now()
					les.dashboard.RecordTrade("BUY", marketID, book.BestAskParsed, positionSize)
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

		// LOSS EXIT: Sell inventory if price drops below 0.70
		// Not scaled — always exit fully regardless of cooldown state
		if lossExitMet && minSizeForLossExit {
			ownedShares := les.ownedInventory[marketID]
			if ownedShares > 0 {
				positionSize := math.Min(
					(maxPosSize*0.5)/book.BestBidParsed,
					book.BestBidSizeParsed*0.5,
				)
				if positionSize > ownedShares {
					positionSize = ownedShares
				}

				if positionSize > 0.5 {
					les.lastTradeTime = time.Now()
					les.dashboard.RecordTrade("SELL", marketID, book.BestBidParsed, positionSize)
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
func (les *LateEntryStrategy) OnOrderPlaced(marketID string, side string, price float64, size float64) {
	if side == "BUY" {
		les.ownedInventory[marketID] += size
		costBasis := price * size
		les.marketExposure[marketID] += costBasis
		les.dashboard.UpdatePosition(marketID, les.ownedInventory[marketID], les.marketExposure[marketID])
	} else if side == "SELL" {
		les.ownedInventory[marketID] -= size
		if les.ownedInventory[marketID] < 0 {
			les.ownedInventory[marketID] = 0
		}
		costBasis := price * size
		les.marketExposure[marketID] -= costBasis
		if les.marketExposure[marketID] < 0 {
			les.marketExposure[marketID] = 0
		}
		les.dashboard.UpdatePosition(marketID, les.ownedInventory[marketID], les.marketExposure[marketID])
	}
}

// OnMarketWindowChange is called when a new 5-minute window begins
func (les *LateEntryStrategy) OnMarketWindowChange() {
	les.windowStartTime = time.Now()
	les.lastCheckTime = time.Now()
	les.ownedInventory = make(map[string]float64)
	les.marketExposure = make(map[string]float64)

	if les.lossTracker != nil {
		go func() {
			_, err := les.lossTracker.CheckForNewLosses()
			if err == nil {
				cooldowns := les.lossTracker.GetActiveCooldowns()
				for title, cd := range cooldowns {
					remaining := cd.CooldownEndTime.Sub(time.Now())
					les.dashboard.SetActiveCooldown(title, cd.RiskMultiplier, remaining)
				}
			}

			for marketSlug := range les.currentMarketsSlugs {
				les.lossTracker.QueueMarketForLossCheck(marketSlug)
			}

			les.currentMarketsSlugs = make(map[string]bool)
		}()
	} else {
		les.currentMarketsSlugs = make(map[string]bool)
	}
}

// Reset clears internal state
func (les *LateEntryStrategy) Reset() {
	les.windowStartTime = time.Now()
	les.lastCheckTime = time.Now()
	les.currentMarketsSlugs = make(map[string]bool)
	les.ownedInventory = make(map[string]float64)
	les.marketExposure = make(map[string]float64)
	les.lastTradeTime = time.Time{}
	if les.lossCheckTicker != nil {
		les.lossCheckTicker.Stop()
	}
}

// boolToCheck converts a boolean to a visual indicator (✓ or ✗)
func boolToCheck(b bool) string {
	if b {
		return "✓"
	}
	return "✗"
}