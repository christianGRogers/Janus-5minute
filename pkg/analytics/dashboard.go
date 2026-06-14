package analytics

import (
	"fmt"
	"os"
	"sync"
	"time"
)

// SwayModelState holds the latest sway model prediction and input features for display.
type SwayModelState struct {
	MarketID        string
	Outcome         string  // "UP" or "DOWN"
	Confidence      float64 // 0.0 – 1.0
	RawPrediction   float64
	FeaturesOK      bool
	RemainingAtPred int // seconds remaining when inference ran
	PredictedAt     time.Time

	// Per-window sway_last values (directional momentum, keyed by window seconds)
	SwayValues    map[int]float64 // e.g. {10: 0.084, 15: 0.062, 20: 0.051, 30: 0.031, 60: 0.015}
	SwayAgreement float64
	SwayMagnitude float64
	ShortLongDiv  float64
}

// Dashboard provides minimal, static terminal output that doesn't scroll visually
// All information is displayed in a locked dashboard format that updates in-place
type Dashboard struct {
	mu                    sync.Mutex
	lastUpdateTime        time.Time
	updateFrequencyMs     int

	// Current state
	currentTime           time.Time
	riskScore             float64
	safetyLevel           string
	riskMultiplier        float64
	lossMultiplier        float64
	combinedMultiplier    float64

	// Market positions
	positions             map[string]PositionInfo // marketID -> position

	// Account info
	balance               float64
	initialBalance        float64
	totalProfit           float64
	totalLoss             float64
	netPnL                float64

	// Loss cooldown
	activeCooldowns       map[string]CooldownInfo // marketID -> cooldown

	// Trading activity (last trade only)
	lastTradeSide         string
	lastTradeMarket       string
	lastTradePrice        float64
	lastTradeSize         float64
	lastTradeTime         time.Time

	// Current market info
	currentMarkets        map[string]MarketInfo // marketID -> current market data

	// Sway model state (latest prediction + features)
	swayState             *SwayModelState
}

// MarketInfo holds current market book data
type MarketInfo struct {
	MarketID    string
	BidPrice    float64
	BidSize     float64
	AskPrice    float64
	AskSize     float64
	Liquidity   float64
	Spread      float64 // percentage
}

// PositionInfo holds current market position data
type PositionInfo struct {
	Shares     float64
	Cost       float64 // USDC spent
	LastPrice  float64
}

// CooldownInfo holds loss cooldown status
type CooldownInfo struct {
	RiskMultiplier float64
	ExpiresIn      time.Duration
}

// NewDashboard creates a new dashboard with minimal update frequency
func NewDashboard(initialBalance float64) *Dashboard {
	return &Dashboard{
		lastUpdateTime:     time.Now(),
		updateFrequencyMs:  1000, // Update every 1 second to keep logs minimal
		initialBalance:     initialBalance,
		balance:            initialBalance,
		positions:          make(map[string]PositionInfo),
		activeCooldowns:    make(map[string]CooldownInfo),
		currentMarkets:     make(map[string]MarketInfo),
	}
}

// ShouldUpdate checks if enough time has passed to warrant a display update
func (d *Dashboard) ShouldUpdate() bool {
	elapsed := time.Since(d.lastUpdateTime).Milliseconds()
	return elapsed >= int64(d.updateFrequencyMs)
}

// SetRiskState updates the current risk metrics
func (d *Dashboard) SetRiskState(riskScore float64, safetyLevel string, riskMultiplier, lossMultiplier, combined float64) {
	d.mu.Lock()
	defer d.mu.Unlock()
	
	d.currentTime = time.Now()
	d.riskScore = riskScore
	d.safetyLevel = safetyLevel
	d.riskMultiplier = riskMultiplier
	d.lossMultiplier = lossMultiplier
	d.combinedMultiplier = combined
}

// SetBalance updates account balance
func (d *Dashboard) SetBalance(balance float64) {
	d.mu.Lock()
	defer d.mu.Unlock()
	
	d.balance = balance
	d.netPnL = balance - d.initialBalance
	if d.netPnL > 0 {
		d.totalProfit = d.netPnL
	} else {
		d.totalLoss = -d.netPnL
	}
}

// UpdatePosition tracks or updates a market position
func (d *Dashboard) UpdatePosition(marketID string, shares float64, cost float64) {
	d.mu.Lock()
	defer d.mu.Unlock()
	
	if shares > 0.1 {
		d.positions[marketID] = PositionInfo{
			Shares:    shares,
			Cost:      cost,
			LastPrice: 0, // Will be updated separately
		}
	} else {
		delete(d.positions, marketID)
	}
}

// SetPositionPrice updates the last price for a position
func (d *Dashboard) SetPositionPrice(marketID string, price float64) {
	d.mu.Lock()
	defer d.mu.Unlock()
	
	if pos, exists := d.positions[marketID]; exists {
		pos.LastPrice = price
		d.positions[marketID] = pos
	}
}

// SetActiveCooldown tracks an active loss cooldown
func (d *Dashboard) SetActiveCooldown(marketID string, multiplier float64, expiresIn time.Duration) {
	d.mu.Lock()
	defer d.mu.Unlock()
	
	if expiresIn > 0 {
		d.activeCooldowns[marketID] = CooldownInfo{
			RiskMultiplier: multiplier,
			ExpiresIn:      expiresIn,
		}
	} else {
		delete(d.activeCooldowns, marketID)
	}
}

// RecordTrade records the last trade executed
func (d *Dashboard) RecordTrade(side, marketID string, price, size float64) {
	d.mu.Lock()
	defer d.mu.Unlock()
	
	d.lastTradeSide = side
	d.lastTradeMarket = marketID
	d.lastTradePrice = price
	d.lastTradeSize = size
	d.lastTradeTime = time.Now()
}

// UpdateMarketData updates the current market book data
func (d *Dashboard) UpdateMarketData(marketID string, bidPrice, bidSize, askPrice, askSize, liquidity, spread float64) {
	d.mu.Lock()
	defer d.mu.Unlock()
	if len(d.currentMarkets) >= 2{
		d.currentMarkets = make(map[string]MarketInfo) // Clear current markets before updating
	}
	d.currentMarkets[marketID] = MarketInfo{
		MarketID:  marketID,
		BidPrice:  bidPrice,
		BidSize:   bidSize,
		AskPrice:  askPrice,
		AskSize:   askSize,
		Liquidity: liquidity,
		Spread:    spread,
	}
}

// SetSwayState updates the displayed sway model prediction and input features.
func (d *Dashboard) SetSwayState(state *SwayModelState) {
	d.mu.Lock()
	defer d.mu.Unlock()
	d.swayState = state
}

// Render outputs the dashboard to the terminal (static format that updates in place)
// Uses ANSI codes to clear lines and reposition cursor
func (d *Dashboard) Render() {
	d.mu.Lock()
	defer d.mu.Unlock()
	
	if !d.ShouldUpdate() {
		return
	}
	
	d.lastUpdateTime = time.Now()
	
	// Clear screen and position at top (this creates the "locked" effect)
	// Using \033[H to go to home position and \033[2J to clear screen
	fmt.Fprint(os.Stdout, "\033[2J\033[H") // Clear screen and go home
	
	// ============ HEADER ============
	fmt.Printf("╔════════════════════════════════════════════════════════════════╗\n")
	fmt.Printf("║          🤖 JANUS TRADING BOT - LIVE DASHBOARD                 ║\n")
	fmt.Printf("╚════════════════════════════════════════════════════════════════╝\n\n")
	
	// ============ TIME & RISK SECTION ============
	fmt.Printf("⏰ TIME: %02d:%02d:%02d  |  ", d.currentTime.Hour(), d.currentTime.Minute(), d.currentTime.Second())
	fmt.Printf("RISK: %.4f (%s) → Position Multiplier: %.2f\n", d.riskScore, d.safetyLevel, d.riskMultiplier)
	
	// ============ LOSS COOLDOWN SECTION ============
	if len(d.activeCooldowns) > 0 {
		fmt.Printf("\n⚠️  LOSS COOLDOWNS ACTIVE:\n")
		for market, cooldown := range d.activeCooldowns {
			fmt.Printf("   • %s: %.2fx multiplier (expires in %.0fm)\n", market, cooldown.RiskMultiplier, cooldown.ExpiresIn.Minutes())
		}
	} else {
		fmt.Printf("\n✓  No active cooldowns\n")
	}
	
	// ============ ACCOUNT SECTION ============
	fmt.Printf("\n💰 ACCOUNT:\n")
	fmt.Printf("   Balance: $%.2f  |  P&L: $%.2f  |  Initial: $%.2f\n", d.balance, d.netPnL, d.initialBalance)
	
	// ============ MARKET DATA SECTION ============
	if len(d.currentMarkets) > 0 {
		fmt.Printf("\n📊 MARKET DATA (%d markets):\n", len(d.currentMarkets))
		for _, market := range d.currentMarkets {
			midPrice := (market.BidPrice + market.AskPrice) / 2
			if midPrice == 0 {
				midPrice = market.BidPrice
				if midPrice == 0 {
					midPrice = market.AskPrice
				}
			}
			fmt.Printf("   • %s: Bid $%.4f (%.0f) | Ask $%.4f (%.0f) | Spread: %.2f%% | Liquidity: $%.0f\n",
				market.MarketID, market.BidPrice, market.BidSize, market.AskPrice, market.AskSize, market.Spread, market.Liquidity)
		}
	} else {
		fmt.Printf("\n📊 MARKET DATA: Waiting for market data...\n")
	}
	
	// ============ POSITIONS SECTION ============
	if len(d.positions) > 0 {
		fmt.Printf("\n📈 POSITIONS (%d):\n", len(d.positions))
		for marketID, pos := range d.positions {
			marketValue := pos.Shares * pos.LastPrice
			pnl := marketValue - pos.Cost
			fmt.Printf("   • %s: %.0f shares @ $%.4f (cost: $%.2f, value: $%.2f, p/l: $%.2f)\n",
				marketID, pos.Shares, pos.LastPrice, pos.Cost, marketValue, pnl)
		}
	} else {
		fmt.Printf("\n📈 POSITIONS: None\n")
	}
	
	// ============ LAST TRADE SECTION ============
	if !d.lastTradeTime.IsZero() {
		elapsed := time.Since(d.lastTradeTime).Seconds()
		fmt.Printf("\n🔄 LAST TRADE: %s %.0f shares of %s @ $%.4f (%.0fs ago)\n",
			d.lastTradeSide, d.lastTradeSize, d.lastTradeMarket, d.lastTradePrice, elapsed)
	} else {
		fmt.Printf("\n🔄 LAST TRADE: None\n")
	}

	// ============ SWAY MODEL SECTION ============
	fmt.Printf("\n🧠 SWAY MODEL:\n")
	if d.swayState != nil && d.swayState.FeaturesOK {
		s := d.swayState
		age := time.Since(s.PredictedAt).Seconds()

		// Confidence bar (20 chars wide)
		filled := int(s.Confidence * 20)
		bar := ""
		for i := 0; i < 20; i++ {
			if i < filled {
				bar += "█"
			} else {
				bar += "░"
			}
		}

		fmt.Printf("   Market:     %s\n", s.MarketID)
		fmt.Printf("   Prediction: %-4s  Raw: %.4f  Conf: %.1f%%  [%s]\n",
			s.Outcome, s.RawPrediction, s.Confidence*100, bar)
		fmt.Printf("   Predicted at %ds remaining  (%.0fs ago)\n", s.RemainingAtPred, age)
		fmt.Printf("   Sway signals (last value per window):\n")
		for _, w := range []int{10, 15, 20, 30, 60} {
			v := s.SwayValues[w]
			dir := "+"
			if v < 0 {
				dir = ""
			}
			fmt.Printf("     %3ds: %s%.4f", w, dir, v)
		}
		fmt.Printf("\n")
		fmt.Printf("   Agreement: %+.3f  |  Magnitude: %.4f  |  S-L Div: %+.4f\n",
			s.SwayAgreement, s.SwayMagnitude, s.ShortLongDiv)
	} else if d.swayState != nil && !d.swayState.FeaturesOK {
		fmt.Printf("   Waiting for sufficient price history...\n")
	} else {
		fmt.Printf("   No prediction yet (fires at 60s, 30s, 20s, 15s, 10s remaining)\n")
	}

	fmt.Printf("\n────────────────────────────────────────────────────────────────\n\n")
}

// RenderMinimal outputs a one-line status update (for frequent checking)
func (d *Dashboard) RenderMinimal() {
	d.mu.Lock()
	defer d.mu.Unlock()
	
	fmt.Printf("[%02d:%02d:%02d] Risk: %.4f (%s) → %.2fx | Balance: $%.2f | Positions: %d | Last: %s %s\n",
		d.currentTime.Hour(), d.currentTime.Minute(), d.currentTime.Second(),
		d.riskScore, d.safetyLevel, d.combinedMultiplier,
		d.balance, len(d.positions),
		d.lastTradeSide, d.lastTradeMarket,
	)
}

// GetPositionCount returns number of active positions
func (d *Dashboard) GetPositionCount() int {
	d.mu.Lock()
	defer d.mu.Unlock()
	return len(d.positions)
}

// GetNetPnL returns current net P&L
func (d *Dashboard) GetNetPnL() float64 {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.netPnL
}
