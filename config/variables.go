package config

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
)

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
	ApiSecret       string // API secret (for CLOB orders)
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
	// Use Amoy testnet (80002) if DRY_RUN is enabled, otherwise use Polygon mainnet (137)
	chainID := uint64(137) // Polygon mainnet by default
	if os.Getenv("DRY_RUN") == "true" {
		chainID = 80002 // Amoy testnet for dry-run
	}
	
	return &PolymarketConfig{
		ClibAPIEndpoint:     "https://clob.polymarket.com",
		ApiKey:              "YOUR_API_KEY_HERE",
		ApiSecret:           "YOUR_API_SECRET_HERE",
		Passphrase:          "YOUR_PASSPHRASE_HERE",
		PrivateKey:          "YOUR_PRIVATE_KEY_HERE",
		Address:             "YOUR_ETH_ADDRESS_HERE",
		PaperTradingEnabled: false,
		OrderGasLimit:       500000,
		OrderChainID:        chainID,
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

// ===== Risk Scoring Configuration =====

// RiskScoresConfig holds the pre-trained risk scores for each hour (0-23)
type RiskScoresConfig struct {
	GeneratedAt string             `json:"generated_at"`
	ModelType   string             `json:"model_type"`
	Scale       string             `json:"scale"`
	Hours       map[string]float64 `json:"hours"`
}

var (
	// GlobalRiskScores is the singleton instance of loaded risk scores
	GlobalRiskScores RiskScoresConfig
	riskScoresLoaded bool
)

// LoadRiskScores loads the pre-trained risk scores from the JSON configuration file
// This should be called once at application startup
func LoadRiskScores() error {
	if riskScoresLoaded {
		return nil // Already loaded
	}

	// Try multiple paths to find the risk_scores.json file
	possiblePaths := []string{
		"config/risk_scores.json",
		"./config/risk_scores.json",
		filepath.Join(os.Getenv("GOPATH"), "config", "risk_scores.json"),
	}

	var config RiskScoresConfig
	var lastErr error

	for _, path := range possiblePaths {
		data, err := os.ReadFile(path)
		if err == nil {
			err = json.Unmarshal(data, &config)
			if err == nil {
				GlobalRiskScores = config
				riskScoresLoaded = true
				log.Printf("[Risk Config] Loaded risk scores from: %s", path)
				logRiskScoresSummary()
				return nil
			}
			lastErr = err
		}
	}

	return fmt.Errorf("failed to load risk_scores.json from any path: %w", lastErr)
}

// GetRiskScoreForHour returns the risk score (0-1) for a given hour (0-23)
// Returns 0.5 (neutral risk) if the hour is not found
func GetRiskScoreForHour(hour int) float64 {
	if !riskScoresLoaded {
		log.Printf("[Risk Config] WARNING: Risk scores not loaded! Call LoadRiskScores() at startup")
		return 0.5 // Default neutral risk
	}

	if hour < 0 || hour > 23 {
		log.Printf("[Risk Config] Invalid hour: %d (must be 0-23)", hour)
		return 0.5
	}

	hourStr := fmt.Sprintf("%d", hour)
	if score, exists := GlobalRiskScores.Hours[hourStr]; exists {
		return score
	}

	return 0.5 // Default neutral risk
}

// GetSafetyLevel returns a qualitative safety level for a risk score
func GetSafetyLevel(riskScore float64) string {
	if riskScore >= 0.8 {
		return "VERY_SAFE"
	} else if riskScore >= 0.6 {
		return "SAFE"
	} else if riskScore >= 0.4 {
		return "MODERATE"
	} else {
		return "RISKY"
	}
}

// logRiskScoresSummary logs a summary of the loaded risk scores
func logRiskScoresSummary() {
	if len(GlobalRiskScores.Hours) != 24 {
		log.Printf("[Risk Config] WARNING: Expected 24 hours, got %d", len(GlobalRiskScores.Hours))
		return
	}

	// Find safest and riskiest hours
	var safeHour, riskyHour int
	var maxScore, minScore float64 = -1, 2

	for i := 0; i < 24; i++ {
		hourStr := fmt.Sprintf("%d", i)
		if score, exists := GlobalRiskScores.Hours[hourStr]; exists {
			if score > maxScore {
				maxScore = score
				safeHour = i
			}
			if score < minScore {
				minScore = score
				riskyHour = i
			}
		}
	}

	log.Printf("[Risk Config] Risk Scores Loaded - Safest: %02d:00 (%.4f), Riskiest: %02d:00 (%.4f)", 
		safeHour, maxScore, riskyHour, minScore)
}

// IsRiskScoresLoaded returns true if risk scores have been successfully loaded
func IsRiskScoresLoaded() bool {
	return riskScoresLoaded
}

// ReloadRiskScores forces a reload of the risk scores (useful for testing)
func ReloadRiskScores() error {
	riskScoresLoaded = false
	return LoadRiskScores()
}
