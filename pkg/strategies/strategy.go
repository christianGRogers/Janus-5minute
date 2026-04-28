package strategies

import (
	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
	"log"
)

// TradeSignal represents a complete trading signal with all necessary information
type TradeSignal struct {
	ShouldTrade      bool    // Whether to execute the trade
	MarketID         string  // Market to trade
	Side             string  // BUY or SELL
	Price            float64 // Execution price
	Size             float64 // Position size
	AvailableLiquidity float64 // Available liquidity for slippage calculation
	Outcome          string  // Position type (UP or DOWN)
}

// Strategy defines the interface for trading strategies
type Strategy interface {
	// Name returns the strategy name
	Name() string

	// Evaluate analyzes current market data and returns trading signals
	// Returns: (should trade, marketID, side (BUY/SELL), price, size)
	// DEPRECATED: Use EvaluateV2 instead
	Evaluate(markets map[string]*polymarket.MarketBook) (bool, string, string, float64, float64)

	// EvaluateV2 analyzes current market data and returns complete trading signal with liquidity info
	EvaluateV2(markets map[string]*polymarket.MarketBook) *TradeSignal

	// OnOrderPlaced is called after a paper trade is executed
	OnOrderPlaced(marketID string, side string, price float64, size float64)

	// OnMarketWindowChange is called when a new 5-minute window begins
	OnMarketWindowChange()

	// Reset clears any internal state
	Reset()
}

// StrategyConfig holds common configuration for strategies
type StrategyConfig struct {
	MinLiquidityUSDC float64 // Minimum liquidity required to trade
	MaxPositionSize  float64 // Maximum position size in USDC (deprecated - use RiskTolerance instead)
	MinSpread        float64 // Minimum spread percentage to consider a trade
	MaxSpread        float64 // Maximum spread percentage to consider a trade
	RiskTolerance    float64 // Risk tolerance: fraction of balance to risk per trade (0.0 to 1.0)
}

// BaseStrategy provides common functionality for all strategies
type BaseStrategy struct {
	Config StrategyConfig
	Engine *trading.PaperTradingEngine
}

// NewBaseStrategy creates a new base strategy with default config
func NewBaseStrategy(engine *trading.PaperTradingEngine) *BaseStrategy {
	return &BaseStrategy{
		Config: StrategyConfig{
			MinLiquidityUSDC: 10000.0,
			MaxPositionSize:  1000.0,
			MinSpread:        0.5,  // At least 0.5% spread to be worth trading
			MaxSpread:        50.0, // Don't trade if spread is >50% (likely misprice or illiquid)
			RiskTolerance:    0.1,  // Default: risk 10% of balance per trade
		},
		Engine: engine,
	}
}

// GetDynamicPositionSize calculates the maximum position size based on current balance and risk tolerance
// If RiskTolerance is 1.0, can risk entire balance per trade
// If RiskTolerance is 0.1, typical trade is ~10% of balance
// If RiskTolerance is 0.05, typical trade is ~5% of balance
func (bs *BaseStrategy) GetDynamicPositionSize() float64 {
	if bs.Engine == nil {
		return bs.Config.MaxPositionSize
	}
	
	currentBalance := bs.Engine.GetBalance()
	riskTolerance := bs.Config.RiskTolerance
	
	// If RiskTolerance is 0 or negative, fall back to MaxPositionSize
	if riskTolerance <= 0 {
		return bs.Config.MaxPositionSize
	}
	
	// Maximum position size is balance * risk tolerance
	dynamicSize := currentBalance * riskTolerance
	
	// Don't exceed the legacy MaxPositionSize if it's set
	if bs.Config.MaxPositionSize > 0 && dynamicSize > bs.Config.MaxPositionSize {
		dynamicSize = bs.Config.MaxPositionSize
	}
	
	return dynamicSize
}

// Evaluate is a default implementation that does nothing - subclasses should override
func (bs *BaseStrategy) Evaluate(markets map[string]*polymarket.MarketBook) (bool, string, string, float64, float64) {
	log.Printf("BaseStrategy Evaluate called - no logic implemented")
	return false, "", "", 0, 0
}

// EvaluateV2 provides default implementation that wraps Evaluate for backwards compatibility
func (bs *BaseStrategy) EvaluateV2(markets map[string]*polymarket.MarketBook) *TradeSignal {
	shouldTrade, marketID, side, price, size := bs.Evaluate(markets)
	
	// Extract available liquidity from market data
	var availableLiquidity float64
	if book, exists := markets[marketID]; exists && book != nil {
		if side == "BUY" {
			availableLiquidity = book.BestAskSizeParsed
		} else {
			availableLiquidity = book.BestBidSizeParsed
		}
	}
	
	return &TradeSignal{
		ShouldTrade:        shouldTrade,
		MarketID:           marketID,
		Side:               side,
		Price:              price,
		Size:               size,
		AvailableLiquidity: availableLiquidity,
	}
}
