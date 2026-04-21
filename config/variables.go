package config

// PolymarketConfig holds static variables for Polymarket API configuration
type PolymarketConfig struct {
	// API Configuration
	ClibAPIEndpoint string
	ApiKey          string
	PrivateKey      string

	// Market Configuration
	Markets []MarketConfig

	// Trading Configuration
	PaperTradingEnabled bool
	OrderGasLimit       uint64
	OrderChainID        uint64

	// Polling Configuration
	PollIntervalSeconds int
}

// MarketConfig represents a specific market to track
type MarketConfig struct {
	MarketID           string  // Polymarket market ID
	Symbol             string  // e.g., "BTC-5M", "ETH-15M"
	TimeframeMinutes   int     // 5, 15, etc
	MinPositionSize    float64 // Minimum position size in USDC
	MaxPositionSize    float64 // Maximum position size in USDC
	LiquidityThreshold float64 // Minimum liquidity required to trade
}

// DefaultConfig returns a template configuration with placeholder values
func DefaultConfig() *PolymarketConfig {
	return &PolymarketConfig{
		ClibAPIEndpoint:     "https://clob.polymarket.com",
		ApiKey:              "YOUR_API_KEY_HERE",
		PrivateKey:          "YOUR_PRIVATE_KEY_HERE",
		PaperTradingEnabled: true,
		OrderGasLimit:       500000,
		OrderChainID:        137, // Polygon mainnet
		PollIntervalSeconds: 1,
		Markets: []MarketConfig{
			{
				MarketID:           "polymarket-btc-updown-5m-1776809400",
				Symbol:             "BTC-5M",
				TimeframeMinutes:   5,
				MinPositionSize:    10.0,
				MaxPositionSize:    1000.0,
				LiquidityThreshold: 5000.0,
			},
		},
	}
}
