package trading

import (
	"crypto/ed25519"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"math/rand"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"janus-bot/pkg/polymarket"
)

// LiveTradingEngine executes real trades on Polymarket
type LiveTradingEngine struct {
	mu              sync.RWMutex
	client          *polymarket.Client
	apiKey          string
	passphrase      string
	privateKey      string
	address         string
	positions       map[string]*PaperPosition // Track current positions
	tradeHistory    []*PaperTrade             // Track trade history for analytics
	orderIDCounter  int64
	lastBalanceTime time.Time
	lastBalance     float64
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
func NewLiveTradingEngine(client *polymarket.Client, apiKey, passphrase, privateKey, address string) *LiveTradingEngine {
	return &LiveTradingEngine{
		client:         client,
		apiKey:         apiKey,
		passphrase:     passphrase,
		privateKey:     privateKey,
		address:        address,
		positions:      make(map[string]*PaperPosition),
		tradeHistory:   make([]*PaperTrade, 0),
		orderIDCounter: 1000,
	}
}

// GetBalance fetches the real balance from the Polymarket API
func (lte *LiveTradingEngine) GetBalance() float64 {
	lte.mu.RLock()
	defer lte.mu.RUnlock()

	// If we cached balance recently, return it (within 30 seconds)
	if time.Since(lte.lastBalanceTime) < 30*time.Second && lte.lastBalance > 0 {
		return lte.lastBalance
	}

	lte.mu.RUnlock()
	balance := lte.fetchBalanceFromAPI()
	lte.mu.Lock()
	lte.lastBalance = balance
	lte.lastBalanceTime = time.Now()
	return balance
}

// fetchBalanceFromAPI queries the Portfolio API for current balance
// Uses Ed25519 signature authentication as per Polymarket API spec
func (lte *LiveTradingEngine) fetchBalanceFromAPI() float64 {
	// Prepare request
	url := "https://api.polymarket.us/v1/account/balances"
	
	// Create HTTP request
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		log.Printf("❌ Failed to create balance request: %v", err)
		return 0
	}

	// Add authentication headers
	timestamp := strconv.FormatInt(time.Now().UnixMilli(), 10)
	signature, err := lte.createPortfolioAPISignature(timestamp, "GET", "/v1/account/balances")
	if err != nil {
		log.Printf("❌ Failed to sign balance request: %v", err)
		return 0
	}

	req.Header.Set("X-PM-Access-Key", lte.apiKey)
	req.Header.Set("X-PM-Timestamp", timestamp)
	req.Header.Set("X-PM-Signature", signature)
	req.Header.Set("Content-Type", "application/json")

	// Send request
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("❌ Failed to fetch balance: %v", err)
		return 0
	}
	defer resp.Body.Close()

	// Parse response
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("❌ Failed to read balance response: %v", err)
		return 0
	}

	if resp.StatusCode != http.StatusOK {
		log.Printf("❌ Balance API returned status %d: %s", resp.StatusCode, string(body))
		return 0
	}

	var balanceResp GetAccountBalancesResponse
	if err := json.Unmarshal(body, &balanceResp); err != nil {
		log.Printf("❌ Failed to parse balance response: %v", err)
		return 0
	}

	// Find USD balance
	for _, balance := range balanceResp.Balances {
		if balance.Currency == "USD" {
			log.Printf("✅ Current balance: $%.2f USD", balance.CurrentBalance)
			return balance.CurrentBalance
		}
	}

	log.Printf("⚠️  No USD balance found in account balances")
	return 0
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

	// Check balance
	currentBalance := lte.GetBalance()
	requiredBalance := price * size
	if side == "BUY" && requiredBalance > currentBalance {
		return "", fmt.Errorf("insufficient balance: required %.2f USDC, have %.2f USDC", requiredBalance, currentBalance)
	}

	// Create order payload
	orderPayload := lte.buildOrderPayload(marketID, side, price, size)

	// Sign the order
	signature, err := lte.signOrder(orderPayload)
	if err != nil {
		return "", fmt.Errorf("failed to sign order: %w", err)
	}
	orderPayload.Signature = signature

	// Build request
	req := &SendOrderRequest{
		Order:     *orderPayload,
		Owner:     lte.address,
		OrderType: "GTC", // Good-til-canceled
		DeferExec: false,
	}

	// Send to API
	response, err := lte.sendOrderToAPI(req)
	if err != nil {
		return "", fmt.Errorf("failed to send order: %w", err)
	}

	if !response.Success {
		return "", fmt.Errorf("order failed: %s", response.ErrorMsg)
	}

	// Log the trade
	lte.orderIDCounter++
	orderID := response.OrderID
	if orderID == "" {
		orderID = fmt.Sprintf("LIVE-%d", lte.orderIDCounter)
	}

	trade := &PaperTrade{
		OrderID:    orderID,
		MarketID:   marketID,
		Side:       side,
		Price:      price,
		Size:       size,
		Status:     response.Status, // live, matched, or delayed
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

	log.Printf("✅ Live order placed: %s %s %.0f shares @ %.4f (Status: %s)", side, marketID, size, price, response.Status)

	return orderID, nil
}

// buildOrderPayload constructs the order payload for signing
func (lte *LiveTradingEngine) buildOrderPayload(marketID string, side string, price float64, size float64) *OrderPayload {
	// Convert price and size to fixed-point math (6 decimals)
	makerAmount := uint64(size * 1e6)
	takerAmount := uint64((price * size) * 1e6)

	// Swap amounts based on side
	if side == "SELL" {
		makerAmount, takerAmount = takerAmount, makerAmount
	}

	now := time.Now()
	timestamp := now.UnixMilli()
	expiration := now.Add(24 * time.Hour).Unix()

	return &OrderPayload{
		Maker:         lte.address,
		Signer:        lte.address,
		TokenID:       marketID, // This should be the actual token ID
		MakerAmount:   fmt.Sprintf("%d", makerAmount),
		TakerAmount:   fmt.Sprintf("%d", takerAmount),
		Side:          side,
		Expiration:    fmt.Sprintf("%d", expiration),
		Timestamp:     fmt.Sprintf("%d", timestamp),
		Metadata:      "",
		Builder:       "0x0000000000000000000000000000000000000000000000000000000000000000",
		Salt:          rand.Int63(),
		SignatureType: 0, // EOA signature
	}
}

// signOrder signs the order using HMAC
func (lte *LiveTradingEngine) signOrder(payload *OrderPayload) (string, error) {
	// TODO: Implement proper EIP-712 signing
	// For now, use HMAC-SHA256 as placeholder
	// This should use the private key to sign the EIP-712 typed data

	msgToSign := fmt.Sprintf("%s%s%s%s%s%s%s%s",
		payload.Maker,
		payload.Signer,
		payload.TokenID,
		payload.MakerAmount,
		payload.TakerAmount,
		payload.Side,
		payload.Timestamp,
		payload.Salt,
	)

	h := hmac.New(sha256.New, []byte(lte.privateKey))
	h.Write([]byte(msgToSign))
	signature := hex.EncodeToString(h.Sum(nil))

	return "0x" + signature, nil
}

// sendOrderToAPI sends the order to the Polymarket CLOB API
func (lte *LiveTradingEngine) sendOrderToAPI(req *SendOrderRequest) (*SendOrderResponse, error) {
	// Create HTTP request
	url := "https://clob.polymarket.com/order"
	payload, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	httpReq, err := http.NewRequest("POST", url, strings.NewReader(string(payload)))
	if err != nil {
		return nil, fmt.Errorf("failed to create HTTP request: %w", err)
	}

	// Set headers
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("POLY_API_KEY", lte.apiKey)
	httpReq.Header.Set("POLY_ADDRESS", lte.address)
	httpReq.Header.Set("POLY_PASSPHRASE", lte.passphrase)
	httpReq.Header.Set("POLY_TIMESTAMP", strconv.FormatInt(time.Now().Unix(), 10))

	// Add signature header
	signature := lte.createRequestSignature(string(payload))
	httpReq.Header.Set("POLY_SIGNATURE", signature)

	// Send request
	client := &http.Client{Timeout: 10 * time.Second}
	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("failed to send request: %w", err)
	}
	defer resp.Body.Close()

	// Parse response
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	var response SendOrderResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return nil, fmt.Errorf("failed to parse response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return &response, fmt.Errorf("API returned status %d: %s", resp.StatusCode, response.ErrorMsg)
	}

	return &response, nil
}

// createRequestSignature creates HMAC signature for the CLOB order request
func (lte *LiveTradingEngine) createRequestSignature(payload string) string {
	h := hmac.New(sha256.New, []byte(lte.passphrase))
	h.Write([]byte(payload))
	return hex.EncodeToString(h.Sum(nil))
}

// createPortfolioAPISignature creates Ed25519 signature for Portfolio API requests
// Signature of: timestamp + method + path
// Uses the private key to sign, returns base64-encoded signature
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
