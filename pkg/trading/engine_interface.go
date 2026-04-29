package trading

// TradingEngine defines the interface for both paper and live trading
type TradingEngine interface {
	// PlaceOrder places an order with market ID, side, price, and size
	PlaceOrder(marketID string, side string, price float64, size float64) (string, error)

	// PlaceOrderWithMetadata places an order with available liquidity metadata
	PlaceOrderWithMetadata(marketID string, side string, price float64, size float64, availableLiquidity float64) (string, error)

	// PlaceOrderWithOutcome places an order with outcome type (UP/DOWN)
	PlaceOrderWithOutcome(marketID string, side string, price float64, size float64, availableLiquidity float64, outcome string) (string, error)

	// GetBalance returns the current account balance
	// For paper trading: calculated as startingBalance + cumulativeProfit
	// For live trading: fetched from API
	GetBalance() float64

	// GetPositions returns all currently open positions
	GetPositions() map[string]*PaperPosition

	// GetTradeHistory returns all executed trades
	GetTradeHistory() []*PaperTrade

	// CloseMarketPositions closes all positions for a market at exit price
	CloseMarketPositions(marketID string, exitPrice float64) []*ClosedPosition

	// CloseMarketPositionsByOutcome closes positions for a specific outcome at exit price
	CloseMarketPositionsByOutcome(marketID string, outcome string, exitPrice float64) []*ClosedPosition

	// GetCumulativeProfit returns total profit from closed positions
	// For paper trading: sum of P&L from closed positions
	// For live trading: 0 (use GetBalance() instead to track profit)
	GetCumulativeProfit() float64
}
