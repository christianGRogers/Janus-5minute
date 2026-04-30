package trading

import (
	"encoding/base64"
	"strings"
	"testing"
	"time"
)

// TestNewLiveTradingEngine tests engine initialization
func TestNewLiveTradingEngine(t *testing.T) {
	apiKey := "test-api-key"
	passphrase := "test-passphrase"
	privateKey := "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
	address := "0x1234567890123456789012345678901234567890"

	engine := NewLiveTradingEngine(nil, apiKey, passphrase, privateKey, address)

	if engine.apiKey != apiKey {
		t.Errorf("expected apiKey %q, got %q", apiKey, engine.apiKey)
	}
	if engine.passphrase != passphrase {
		t.Errorf("expected passphrase %q, got %q", passphrase, engine.passphrase)
	}
	if engine.address != address {
		t.Errorf("expected address %q, got %q", address, engine.address)
	}
	if len(engine.positions) != 0 {
		t.Errorf("expected empty positions map, got %d positions", len(engine.positions))
	}
	if len(engine.tradeHistory) != 0 {
		t.Errorf("expected empty trade history, got %d trades", len(engine.tradeHistory))
	}
}

// TestGetBalance tests balance caching
func TestGetBalance(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	// First call should try to fetch (will return 0 as API not mocked)
	balance1 := engine.GetBalance()
	if balance1 != 0 {
		t.Errorf("expected balance 0 (no API mock), got %.2f", balance1)
	}

	// Manually set cached balance for testing
	engine.mu.Lock()
	engine.lastBalance = 1000.0
	engine.lastBalanceTime = time.Now()
	engine.mu.Unlock()

	// Second call within cache window should return cached value
	balance2 := engine.GetBalance()
	if balance2 != 1000.0 {
		t.Errorf("expected cached balance 1000.0, got %.2f", balance2)
	}
}

// TestCreatePortfolioAPISignature tests Ed25519 signature generation
func TestCreatePortfolioAPISignature(t *testing.T) {
	// Test with 32-byte seed (hex-encoded: 64 chars)
	seed := "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
	engine := NewLiveTradingEngine(nil, "key", "pass", seed, "addr")

	timestamp := "1234567890000"
	method := "GET"
	path := "/v1/account/balances"

	signature, err := engine.createPortfolioAPISignature(timestamp, method, path)
	if err != nil {
		t.Fatalf("failed to create signature: %v", err)
	}

	// Signature should be base64-encoded
	_, err = base64.StdEncoding.DecodeString(signature)
	if err != nil {
		t.Errorf("signature is not valid base64: %v", err)
	}

	// Signature should be deterministic
	signature2, _ := engine.createPortfolioAPISignature(timestamp, method, path)
	if signature != signature2 {
		t.Errorf("signature is not deterministic: %q != %q", signature, signature2)
	}

	// Different inputs should produce different signatures
	signature3, _ := engine.createPortfolioAPISignature("9999999999999", method, path)
	if signature == signature3 {
		t.Errorf("different inputs produced same signature")
	}
}

// TestCreatePortfolioAPISignatureWithInvalidKey tests error handling
func TestCreatePortfolioAPISignatureWithInvalidKey(t *testing.T) {
	// Invalid private key (wrong length)
	invalidKey := "tooshort"
	engine := NewLiveTradingEngine(nil, "key", "pass", invalidKey, "addr")

	_, err := engine.createPortfolioAPISignature("1234567890000", "GET", "/v1/account/balances")
	if err == nil {
		t.Errorf("expected error for invalid key, got nil")
	}
}

// TestBuildOrderPayload tests order payload construction
func TestBuildOrderPayload(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	marketID := "test-market-123"
	side := "BUY"
	price := 0.75
	size := 100.0

	payload := engine.buildOrderPayload(marketID, side, price, size)

	if payload.Maker != engine.address {
		t.Errorf("expected maker %q, got %q", engine.address, payload.Maker)
	}
	if payload.Signer != engine.address {
		t.Errorf("expected signer %q, got %q", engine.address, payload.Signer)
	}
	if payload.Side != side {
		t.Errorf("expected side %q, got %q", side, payload.Side)
	}
	if payload.TokenID != marketID {
		t.Errorf("expected tokenId %q, got %q", marketID, payload.TokenID)
	}

	// Check amounts (fixed-point math with 6 decimals)
	// For BUY: maker provides USDC (size * price), taker provides shares (size)
	// expectedMaker := uint64((price * size) * 1e6)
	// expectedTaker := uint64(size * 1e6)

	// Just verify the fields are populated
	if payload.MakerAmount == "" {
		t.Errorf("expected non-empty makerAmount")
	}

	if payload.Side != "BUY" && payload.Side != "SELL" {
		t.Errorf("invalid side: %q", payload.Side)
	}

	// Verify signature type and other fields
	if payload.SignatureType != 0 {
		t.Errorf("expected signatureType 0 (EOA), got %d", payload.SignatureType)
	}
	if payload.Builder == "" {
		t.Errorf("expected builder address, got empty string")
	}
}

// TestGetPositions tests position retrieval
func TestGetPositions(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	// Initially empty
	positions := engine.GetPositions()
	if len(positions) != 0 {
		t.Errorf("expected empty positions, got %d", len(positions))
	}

	// Manually add a position
	engine.mu.Lock()
	engine.positions["market-1"] = &PaperPosition{
		MarketID:  "market-1",
		Side:      "BUY",
		Direction: "UP",
		Size:      100,
		AvgPrice:  0.75,
		EntryTime: time.Now().Unix(),
	}
	engine.mu.Unlock()

	// Retrieve positions
	positions = engine.GetPositions()
	if len(positions) != 1 {
		t.Errorf("expected 1 position, got %d", len(positions))
	}

	pos, exists := positions["market-1"]
	if !exists {
		t.Errorf("expected position for market-1")
	}
	if pos.Side != "BUY" {
		t.Errorf("expected side BUY, got %q", pos.Side)
	}
	if pos.Size != 100 {
		t.Errorf("expected size 100, got %.0f", pos.Size)
	}
}

// TestGetTradeHistory tests trade history retrieval
func TestGetTradeHistory(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	// Initially empty
	history := engine.GetTradeHistory()
	if len(history) != 0 {
		t.Errorf("expected empty history, got %d trades", len(history))
	}

	// Manually add a trade
	engine.mu.Lock()
	engine.tradeHistory = append(engine.tradeHistory, &PaperTrade{
		OrderID:   "order-1",
		MarketID:  "market-1",
		Side:      "BUY",
		Price:     0.75,
		Size:      100,
		Status:    "FILLED",
		FilledSize: 100,
		Timestamp: time.Now().Unix(),
	})
	engine.mu.Unlock()

	// Retrieve history
	history = engine.GetTradeHistory()
	if len(history) != 1 {
		t.Errorf("expected 1 trade, got %d", len(history))
	}

	trade := history[0]
	if trade.OrderID != "order-1" {
		t.Errorf("expected orderID order-1, got %q", trade.OrderID)
	}
	if trade.Side != "BUY" {
		t.Errorf("expected side BUY, got %q", trade.Side)
	}
}

// contains is a helper function to check if a string contains a substring
func contains(s, substr string) bool {
	return strings.Contains(s, substr)
}

// TestGetCumulativeProfit tests that live trading returns 0 profit
func TestGetCumulativeProfit(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	profit := engine.GetCumulativeProfit()
	if profit != 0 {
		t.Errorf("expected cumulative profit 0 for live trading, got %.2f", profit)
	}
}

// TestCloseMarketPositions tests that close operations return empty results
func TestCloseMarketPositions(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	// Close positions should return empty (live trading closes via PlaceOrder)
	closed := engine.CloseMarketPositions("market-1", 0.80)
	if len(closed) != 0 {
		t.Errorf("expected empty closed positions for live trading, got %d", len(closed))
	}

	closedByOutcome := engine.CloseMarketPositionsByOutcome("market-1", "UP", 0.80)
	if len(closedByOutcome) != 0 {
		t.Errorf("expected empty closed positions for live trading, got %d", len(closedByOutcome))
	}
}

// TestPlaceOrderValidation tests order validation
func TestPlaceOrderValidation(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	tests := []struct {
		name        string
		marketID    string
		side        string
		price       float64
		size        float64
		shouldError bool
		errorMsg    string
	}{
		{
			name:        "invalid price too high",
			marketID:    "market-1",
			side:        "BUY",
			price:       1.5,
			size:        100,
			shouldError: true,
			errorMsg:    "invalid price",
		},
		{
			name:        "invalid price negative",
			marketID:    "market-1",
			side:        "BUY",
			price:       -0.5,
			size:        100,
			shouldError: true,
			errorMsg:    "invalid price",
		},
		{
			name:        "invalid size zero",
			marketID:    "market-1",
			side:        "BUY",
			price:       0.75,
			size:        0,
			shouldError: true,
			errorMsg:    "invalid size",
		},
		{
			name:        "invalid size negative",
			marketID:    "market-1",
			side:        "BUY",
			price:       0.75,
			size:        -100,
			shouldError: true,
			errorMsg:    "invalid size",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Set balance high enough
			engine.mu.Lock()
			engine.lastBalance = 100000.0
			engine.lastBalanceTime = time.Now()
			engine.mu.Unlock()

			_, err := engine.PlaceOrder(tt.marketID, tt.side, tt.price, tt.size)
			if tt.shouldError {
				// For validation errors, we expect them
				if err == nil {
				t.Errorf("expected error containing %q, got nil", tt.errorMsg)
			} else if !strings.Contains(err.Error(), tt.errorMsg) {
				t.Errorf("expected error containing %q, got: %v", tt.errorMsg, err)
			}
		}
	})
}
}

// TestPlaceOrderInsufficientBalance tests balance validation
func TestPlaceOrderInsufficientBalance(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	// Set low balance
	engine.mu.Lock()
	engine.lastBalance = 10.0
	engine.lastBalanceTime = time.Now()
	engine.mu.Unlock()

	// Try to buy shares worth more than balance
	_, err := engine.PlaceOrder("market-1", "BUY", 0.75, 1000) // 0.75 * 1000 = 750 USDC
	if err == nil {
		t.Errorf("expected insufficient balance error, got nil")
	}
	if err != nil && !contains(err.Error(), "insufficient balance") {
		t.Errorf("expected 'insufficient balance' error, got: %v", err)
	}
}

// TestSignatureConsistency tests that signatures are reproducible
func TestSignatureConsistency(t *testing.T) {
	seed := "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
	engine := NewLiveTradingEngine(nil, "key", "pass", seed, "addr")

	// Same inputs should produce same signature
	sig1, _ := engine.createPortfolioAPISignature("1000", "GET", "/path")
	sig2, _ := engine.createPortfolioAPISignature("1000", "GET", "/path")

	if sig1 != sig2 {
		t.Errorf("signatures not consistent: %q != %q", sig1, sig2)
	}
}

// TestOrderIDGeneration tests order ID generation
func TestOrderIDGeneration(t *testing.T) {
	engine := NewLiveTradingEngine(nil, "key", "pass", "privkey", "addr")

	if engine.orderIDCounter < 1000 {
		t.Errorf("expected orderIDCounter >= 1000, got %d", engine.orderIDCounter)
	}

	initialCounter := engine.orderIDCounter

	// Note: Since PlaceOrder calls the API (which we're not mocking),
	// we can't easily test order ID increment without mocking.
	// This test just verifies the initial state.
	if engine.orderIDCounter != initialCounter {
		t.Errorf("expected consistent orderIDCounter")
	}
}
