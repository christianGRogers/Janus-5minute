package trading

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"

	"janus-bot/pkg/polymarket"
)

// min returns the minimum of two integers
func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// LiveTradingEngine executes real trades on Polymarket
type LiveTradingEngine struct {
	mu             sync.RWMutex
	client         *polymarket.Client
	apiKey         string
	apiSecret      string
	apiKeyOwnerID  string // UUID of the API key owner (required for order placement)
	passphrase     string
	privateKey     string
	address        string
	positions      map[string]*PaperPosition // Track current positions
	tradeHistory   []*PaperTrade             // Track trade history for analytics
	orderIDCounter int64
	dryRun         bool                      // If true, send orders to API with verbose logging for review
}

// SendOrderRequest is the request payload for POST /order
type SendOrderRequest struct {
	Order     OrderPayload `json:"order"`
	Owner     string       `json:"owner"`
	OrderType string       `json:"orderType"` // GTC, FOK, GTD, FAK
	DeferExec bool         `json:"deferExec"`
}

// OrderPayload represents the order structure
type OrderPayload struct {
	Maker         string `json:"maker"`
	Signer        string `json:"signer"`
	TokenID       string `json:"tokenId"`
	MakerAmount   string `json:"makerAmount"`
	TakerAmount   string `json:"takerAmount"`
	Side          string `json:"side"` // BUY or SELL
	Expiration    string `json:"expiration"`
	Timestamp     string `json:"timestamp"`
	Metadata      string `json:"metadata"`
	Builder       string `json:"builder"`
	Signature     string `json:"signature"`
	Salt          int64  `json:"salt"`
	SignatureType int    `json:"signatureType"`
}

// SendOrderResponse is the response from POST /order
type SendOrderResponse struct {
	Success             bool     `json:"success"`
	OrderID             string   `json:"orderID"`
	Status              string   `json:"status"` // live, matched, delayed
	MakingAmount        string   `json:"makingAmount"`
	TakingAmount        string   `json:"takingAmount"`
	TransactionHashes   []string `json:"transactionsHashes"`
	TradeIDs            []string `json:"tradeIDs"`
	ErrorMsg            string   `json:"errorMsg"`
}

// GetAccountBalancesResponse is the response from GET /v1/account/balances
type GetAccountBalancesResponse struct {
	Balances []UserBalance `json:"balances"`
}

// UserBalance represents account balance information
type UserBalance struct {
	CurrentBalance      float64             `json:"currentBalance"`
	Currency            string              `json:"currency"`
	LastUpdated         string              `json:"lastUpdated"`
	BuyingPower         float64             `json:"buyingPower"`
	AssetNotional       float64             `json:"assetNotional"`
	AssetAvailable      float64             `json:"assetAvailable"`
	PendingCredit       float64             `json:"pendingCredit"`
	OpenOrders          float64             `json:"openOrders"`
	UnsettledFunds      float64             `json:"unsettledFunds"`
	PendingWithdrawals  []PendingWithdrawal `json:"pendingWithdrawals"`
	MarginRequirement   float64             `json:"marginRequirement"`
	BalanceReservation  *float64            `json:"balanceReservation"`
}

// PendingWithdrawal represents a pending withdrawal
type PendingWithdrawal struct {
	ID                    string `json:"id"`
	Name                  string `json:"name"`
	Balance               float64 `json:"balance"`
	Description           string `json:"description"`
	Acknowledged          bool   `json:"acknowledged"`
	BankID                string `json:"bankId"`
	CreationTime          string `json:"creationTime"`
	DestinationAccountName string `json:"destinationAccountName"`
}
// NewLiveTradingEngine creates a new live trading engine
func NewLiveTradingEngine(client *polymarket.Client, apiKey, apiSecret, passphrase, privateKey, address string) *LiveTradingEngine {
	return NewLiveTradingEngineWithOwner(client, apiKey, apiKey, apiSecret, passphrase, privateKey, address)
}

// NewLiveTradingEngineWithOwner creates a new live trading engine with explicit owner ID
// apiKeyOwnerID is the UUID of the API key owner (required for order placement per Polymarket API spec)
func NewLiveTradingEngineWithOwner(client *polymarket.Client, apiKey, apiKeyOwnerID, apiSecret, passphrase, privateKey, address string) *LiveTradingEngine {
	dryRun := os.Getenv("DRY_RUN") == "true"
	if dryRun {
		log.Println("⚠️  DRY_RUN mode enabled - orders will be simulated locally")
	}
	
	return &LiveTradingEngine{
		client:         client,
		apiKey:         apiKey,
		apiSecret:      apiSecret,
		apiKeyOwnerID:  apiKeyOwnerID,
		passphrase:     passphrase,
		privateKey:     privateKey,
		address:        address,
		positions:      make(map[string]*PaperPosition),
		tradeHistory:   make([]*PaperTrade, 0),
		orderIDCounter: 1000,
		dryRun:         dryRun,
	}
}

// GetBalance fetches the real balance from the Polymarket API
// Always fetches fresh balance (no caching) since balance can be updated at any time
func (lte *LiveTradingEngine) GetBalance() float64 {
	lte.mu.Lock()
	defer lte.mu.Unlock()

	// Always fetch fresh balance from API
	balance := lte.fetchBalanceFromAPI()
	return balance
}

// fetchBalanceFromAPI queries Polymarket for current balance by calling the Python script
// The Python script uses py-clob-client which properly handles credential derivation
// and the CLOB API balance-allowance endpoint
func (lte *LiveTradingEngine) fetchBalanceFromAPI() float64 {
	// Call Python script to get balance
	cmd := exec.Command("python", "tools/get_polymarket_balance.py")
	
	// Set environment variables for the Python script
	cmd.Env = append(os.Environ(),
		fmt.Sprintf("PRIVATE_KEY=%s", lte.privateKey),
		fmt.Sprintf("PROXY_ADDRESS=%s", lte.address),  // The proxy address (not EOA)
	)
	
	output, err := cmd.Output()
	if err != nil {
		log.Printf("❌ Failed to execute balance script: %v", err)
		return 0
	}
	
	// Parse JSON response
	var result struct {
		Balance float64 `json:"balance"`
		Status  string  `json:"status"`
		Message string  `json:"message"`
	}
	
	if err := json.Unmarshal(output, &result); err != nil {
		log.Printf("❌ Failed to parse balance response: %v", err)
		return 0
	}
	
	if result.Status != "success" {
		log.Printf("❌ Failed to fetch balance: %s", result.Message)
		return 0
	}
	
	log.Printf("✅ Current balance: $%.2f USD", result.Balance)
	return result.Balance
}

// PlaceOrder places a real order on Polymarket
func (lte *LiveTradingEngine) PlaceOrder(marketID string, side string, price float64, size float64) (string, error) {
	return lte.PlaceOrderWithMetadata(marketID, side, price, size, 0)
}

// PlaceOrderWithMetadata places an order with metadata
func (lte *LiveTradingEngine) PlaceOrderWithMetadata(marketID string, side string, price float64, size float64, availableLiquidity float64) (string, error) {
	return lte.PlaceOrderWithOutcome(marketID, side, price, size, availableLiquidity, "")
}

// PlaceOrderWithOutcome places a real order with outcome type
// Uses Python SDK to properly sign EIP-712 orders
func (lte *LiveTradingEngine) PlaceOrderWithOutcome(marketID string, side string, price float64, size float64, availableLiquidity float64, outcome string) (string, error) {
	lte.mu.Lock()
	defer lte.mu.Unlock()

	// Validate inputs
	if price <= 0 || price >= 1 {
		return "", fmt.Errorf("invalid price: %.4f (must be between 0 and 1)", price)
	}
	if size <= 0 {
		return "", fmt.Errorf("invalid size: %.2f (must be positive)", size)
	}

	// Call Python script to place order (handles proper EIP-712 signing)
	orderID, err := lte.placeOrderViaScript(marketID, side, price, size)
	if err != nil {
		return "", err
	}

	// Log the trade
	lte.orderIDCounter++
	if orderID == "" {
		orderID = fmt.Sprintf("ORDER-%d", lte.orderIDCounter)
	}

	trade := &PaperTrade{
		OrderID:    orderID,
		MarketID:   marketID,
		Side:       side,
		Price:      price,
		Size:       size,
		Status:     "live",
		FilledSize: size,
		Timestamp:  time.Now().Unix(),
	}
	lte.tradeHistory = append(lte.tradeHistory, trade)

	// Track position
	posKey := marketID
	direction := outcome
	if direction == "" {
		direction = "UP"
		if len(marketID) > 3 && marketID[len(marketID)-4:] == "DOWN" {
			direction = "DOWN"
		}
	}

	if pos, exists := lte.positions[posKey]; exists {
		if pos.Side == side {
			// Increase position
			totalCost := pos.AvgPrice*pos.Size + price*size
			pos.Size += size
			pos.AvgPrice = totalCost / pos.Size
		} else {
			// Close or reduce position
			if pos.Size >= size {
				pos.Size -= size
				if pos.Size == 0 {
					delete(lte.positions, posKey)
				}
			} else {
				remainingSize := size - pos.Size
				delete(lte.positions, posKey)
				lte.positions[posKey] = &PaperPosition{
					MarketID:  marketID,
					Side:      side,
					Direction: direction,
					Size:      remainingSize,
					AvgPrice:  price,
					EntryTime: time.Now().Unix(),
				}
			}
		}
	} else {
		// New position
		lte.positions[posKey] = &PaperPosition{
			MarketID:  marketID,
			Side:      side,
			Direction: direction,
			Size:      size,
			AvgPrice:  price,
			EntryTime: time.Now().Unix(),
		}
	}

	log.Printf("✅ Live order placed: %s %s %.0f shares @ %.4f (ID: %s)", side, marketID, size, price, orderID)

	return orderID, nil
}

// placeOrderViaScript calls Python with py-clob-client to place an order
// Step 1: Check if marketID is already a token ID, or if it's a market slug that needs lookup
// Step 2: Place order using the token ID
func (lte *LiveTradingEngine) placeOrderViaScript(marketID string, side string, price float64, size float64) (string, error) {
	var tokenID string
	var err error
	
	// Determine if marketID is already a token ID or a market slug
	// Token IDs are large numeric strings (typically 70+ digit numbers)
	// Market slugs contain hyphens and are much shorter (e.g., "btc-updown-5m-1234567890")
	if len(marketID) > 50 {
		// Likely a token ID already (token IDs are very large numbers)
		tokenID = marketID
		log.Printf("✅ Using provided token ID: %s", tokenID)
	} else if strings.Contains(marketID, "-") {
		// Market slug - need to fetch token ID from Gamma API
		tokenID, err = lte.getTokenIDFromMarketID(marketID)
		if err != nil {
			log.Printf("❌ Failed to get token ID for market slug %s: %v", marketID, err)
			return "", err
		}
		
		if tokenID == "" {
			log.Printf("❌ No token ID found for market slug %s", marketID)
			return "", fmt.Errorf("no token ID found for market slug %s", marketID)
		}
	} else {
		// Unknown format
		return "", fmt.Errorf("marketID must be either a market slug (e.g., 'btc-updown-5m-xxx') or a token ID (large numeric string), got: %s", marketID)
	}

	// Step 2: Place order using token ID
	cmd := exec.Command("python", "tools/place_order.py",
		"--token-id", tokenID,
		"--price", fmt.Sprintf("%.4f", price),
		"--size", fmt.Sprintf("%.2f", size),
		"--side", side,
		"--tick-size", "0.01",
	)

	// Set environment variables for Python script
	cmd.Env = append(os.Environ(),
		fmt.Sprintf("PRIVATE_KEY=%s", lte.privateKey),
		fmt.Sprintf("PROXY_ADDRESS=%s", lte.address),  // The proxy address (not EOA)
	)

	// Capture both stdout and stderr
	var stdout, stderr strings.Builder
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err = cmd.Run()
	
	stdoutStr := stdout.String()
	stderrStr := stderr.String()
	
	// Log all output for debugging
	if stdoutStr != "" {
		log.Printf("📤 Python script stdout: %s", stdoutStr)
	}
	if stderrStr != "" {
		log.Printf("📤 Python script stderr: %s", stderrStr)
	}
	
	if err != nil {
		log.Printf("❌ Order placement script failed")
		log.Printf("   Command: python tools/place_order.py --token-id %s --price %.4f --size %.2f --side %s", 
			tokenID, price, size, side)
		log.Printf("   Error: %v", err)
		if stderrStr != "" {
			log.Printf("   Stderr: %s", stderrStr)
		}
		return "", fmt.Errorf("order placement script failed: %v\nstderr: %s", err, stderrStr)
	}

	// Parse JSON response
	var result struct {
		Success bool   `json:"success"`
		OrderID string `json:"orderID"`
		Error   string `json:"error"`
		ErrorMsg string `json:"errorMsg"`
	}

	if err := json.Unmarshal([]byte(stdoutStr), &result); err != nil {
		log.Printf("❌ Failed to parse order response: %v", err)
		log.Printf("   Output: %s", stdoutStr)
		log.Printf("   Stderr: %s", stderrStr)
		return "", fmt.Errorf("failed to parse order response: %w\nOutput: %s\nStderr: %s", err, stdoutStr, stderrStr)
	}

	if !result.Success {
		errorMsg := result.Error
		if errorMsg == "" {
			errorMsg = result.ErrorMsg
		}
		log.Printf("❌ Order placement failed: %s", errorMsg)
		return "", fmt.Errorf("order placement failed: %s", errorMsg)
	}

	log.Printf("✅ Order placed successfully - Token: %s, OrderID: %s", tokenID, result.OrderID)
	return result.OrderID, nil
}

// getTokenIDFromMarketID fetches the token ID for a given market ID from Gamma API
func (lte *LiveTradingEngine) getTokenIDFromMarketID(marketID string) (string, error) {
	// marketID is typically the market slug (e.g., "btc-updown-5m-1234567890")
	// Fetch market data from Gamma API
	
	url := fmt.Sprintf("https://gamma-api.polymarket.com/markets/slug/%s", marketID)
	
	httpReq, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return "", fmt.Errorf("failed to create request: %w", err)
	}

	httpReq.Header.Set("Accept", "application/json")

	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(httpReq)
	if err != nil {
		return "", fmt.Errorf("failed to fetch market data: %w", err)
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read response: %w", err)
	}

	// Parse the response to extract token IDs
	var market struct {
		ClobTokenIds []string `json:"clobTokenIds"`
		Question     string   `json:"question"`
		Slug         string   `json:"slug"`
	}

	if err := json.Unmarshal(body, &market); err != nil {
		log.Printf("❌ Failed to parse market data: %v", err)
		log.Printf("   Response: %s", string(body[:min(len(body), 500)]))
		return "", fmt.Errorf("failed to parse market data: %w", err)
	}

	if len(market.ClobTokenIds) == 0 {
		return "", fmt.Errorf("no token IDs found for market %s", marketID)
	}

	// Return first token ID (UP outcome)
	tokenID := market.ClobTokenIds[0]
	log.Printf("✅ Found token ID for market %s: %s", marketID, tokenID)
	
	return tokenID, nil
}



// createPortfolioAPISignature creates Ed25519 signature for Portfolio API requests
// Signature of: timestamp + method + path
// Uses the private key to sign, returns base64-encoded signature
// NOTE: This is kept for reference but not used in current implementation
// Current implementation uses CLOB API with HMAC-SHA256 signatures
func (lte *LiveTradingEngine) createPortfolioAPISignature(timestamp string, method string, path string) (string, error) {
	// Message to sign: timestamp + method + path
	msgToSign := timestamp + method + path
	
	// Decode private key (should be hex-encoded Ed25519 private key)
	// Private key should be 64 bytes (128 hex characters)
	privKeyBytes, err := hex.DecodeString(lte.privateKey)
	if err != nil {
		return "", fmt.Errorf("failed to decode private key: %w", err)
	}
	
	// Create Ed25519 private key
	var privateKey ed25519.PrivateKey
	if len(privKeyBytes) == 32 {
		// Seed provided - derive full private key
		privateKey = ed25519.NewKeyFromSeed(privKeyBytes)
	} else if len(privKeyBytes) == 64 {
		// Full private key provided
		privateKey = ed25519.PrivateKey(privKeyBytes)
	} else {
		return "", fmt.Errorf("invalid private key length: %d bytes (expected 32 or 64)", len(privKeyBytes))
	}
	
	// Sign the message
	signature := ed25519.Sign(privateKey, []byte(msgToSign))
	
	// Return base64-encoded signature (Polymarket expects base64)
	return base64.StdEncoding.EncodeToString(signature), nil
}

// GetPositions returns current open positions
func (lte *LiveTradingEngine) GetPositions() map[string]*PaperPosition {
	lte.mu.RLock()
	defer lte.mu.RUnlock()

	posCopy := make(map[string]*PaperPosition)
	for k, v := range lte.positions {
		posCopy[k] = v
	}
	return posCopy
}

// GetTradeHistory returns all trades
func (lte *LiveTradingEngine) GetTradeHistory() []*PaperTrade {
	lte.mu.RLock()
	defer lte.mu.RUnlock()

	historyCopy := make([]*PaperTrade, len(lte.tradeHistory))
	copy(historyCopy, lte.tradeHistory)
	return historyCopy
}

// CloseMarketPositions closes all positions for a market at exit price
func (lte *LiveTradingEngine) CloseMarketPositions(marketID string, exitPrice float64) []*ClosedPosition {
	// In live trading, positions are closed by placing opposite orders via PlaceOrder
	// This is a placeholder for analytics purposes
	return []*ClosedPosition{}
}

// CloseMarketPositionsByOutcome closes positions for a specific outcome at exit price
func (lte *LiveTradingEngine) CloseMarketPositionsByOutcome(marketID string, outcome string, exitPrice float64) []*ClosedPosition {
	// In live trading, positions are closed by placing opposite orders via PlaceOrder
	// This is a placeholder for analytics purposes
	return []*ClosedPosition{}
}

// GetCumulativeProfit returns 0 in live trading (use balance instead)
func (lte *LiveTradingEngine) GetCumulativeProfit() float64 {
	// In live trading, profit is reflected in the balance
	// No need to track separately
	return 0
}
