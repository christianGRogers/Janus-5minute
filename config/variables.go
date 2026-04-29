package config

// PaperTradingRealisticConfig controls realism features for paper trading simulations
type PaperTradingRealisticConfig struct {
	// Slippage modeling: price impact from taking liquidity
	EnableSlippage        bool    // Model price impact from liquidity taken (default: true)
	SlippageFactorPercent float64 // Slippage per % of liquidity taken in basis points (default: 0.5)
	
	// Latency modeling: network/execution delays
	EnableLatency bool // Add realistic 100-500ms execution delays (default: true)
	
	// Price staleness: models price gaps between poll intervals
	EnablePriceStaleness bool    // Model price movement between polls (default: true)
	MaxPriceStalenessBps float64 // Max basis points price can move between polls (default: 50)
}

// DefaultPaperTradingRealistic returns recommended realistic settings for paper trading
func DefaultPaperTradingRealistic() *PaperTradingRealisticConfig {
	return &PaperTradingRealisticConfig{
		EnableSlippage:        true,
		SlippageFactorPercent: 0.5,
		EnableLatency:         true,
		EnablePriceStaleness:  true,
		MaxPriceStalenessBps:  50,
	}
}

// PolymarketConfig holds static variables for Polymarket API configuration
type PolymarketConfig struct {
	// API Configuration
	ClibAPIEndpoint string // CLOB API endpoint (for order placement)
	ApiKey          string // API key ID (UUID)
	Passphrase      string // API key passphrase (for CLOB orders)
	PrivateKey      string // Ed25519 private key, hex-encoded (32 or 64 bytes)
	Address         string // Ethereum address

	// Market Configuration
	Markets []MarketConfig

	// Trading Configuration
	PaperTradingEnabled bool
	OrderGasLimit       uint64
	OrderChainID        uint64

	// Paper Trading Realism
	PaperTradingRealistic *PaperTradingRealisticConfig

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
		Passphrase:          "YOUR_PASSPHRASE_HERE",
		PrivateKey:          "YOUR_PRIVATE_KEY_HERE",
		Address:             "YOUR_ETH_ADDRESS_HERE",
		PaperTradingEnabled: true,
		OrderGasLimit:       500000,
		OrderChainID:        137, // Polygon mainnet
		PollIntervalSeconds: 1,
		PaperTradingRealistic: DefaultPaperTradingRealistic(),
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
