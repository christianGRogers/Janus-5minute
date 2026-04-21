package polymarket

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"time"
)

// Client handles all communication with the Polymarket CLOB API
type Client struct {
	baseURL    string
	apiKey     string
	httpClient *http.Client
}

// NewClient creates a new Polymarket CLOB API client
func NewClient(baseURL, apiKey string) *Client {
	return &Client{
		baseURL: baseURL,
		apiKey:  apiKey,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// OrderLevel represents a single price level in the order book
type OrderLevel struct {
	Price string `json:"price"`
	Size  string `json:"size"`
}

// MarketBook represents the order book for a market
type MarketBook struct {
	Market           string       `json:"market"`
	AssetID          string       `json:"asset_id"`
	Timestamp        string       `json:"timestamp"`
	Hash             string       `json:"hash"`
	Bids             []OrderLevel `json:"bids"`
	Asks             []OrderLevel `json:"asks"`
	MinOrderSize     string       `json:"min_order_size"`
	TickSize         string       `json:"tick_size"`
	NegRisk          bool         `json:"neg_risk"`
	LastTradePrice   string       `json:"last_trade_price"`
	
	// Parsed values
	BestBidParsed     float64
	BestAskParsed     float64
	BestBidSizeParsed float64
	BestAskSizeParsed float64
	TimestampParsed   int64
	LiquidityParsed   float64
}

// ParseBook converts the string values to proper types and calculates derived values
func (mb *MarketBook) ParseBook() error {
	// The bids array is sorted in ASCENDING order, so the best bid (highest) is at the END
	if len(mb.Bids) > 0 {
		// Get the last bid (highest price)
		bid, err := strconv.ParseFloat(mb.Bids[len(mb.Bids)-1].Price, 64)
		if err != nil {
			return fmt.Errorf("failed to parse best bid price: %w", err)
		}
		size, err := strconv.ParseFloat(mb.Bids[len(mb.Bids)-1].Size, 64)
		if err != nil {
			return fmt.Errorf("failed to parse best bid size: %w", err)
		}
		mb.BestBidParsed = bid
		mb.BestBidSizeParsed = size
	}
	
	// The asks array is sorted in DESCENDING order, so the best ask (lowest) is at the END
	if len(mb.Asks) > 0 {
		// Get the last ask (lowest price)
		ask, err := strconv.ParseFloat(mb.Asks[len(mb.Asks)-1].Price, 64)
		if err != nil {
			return fmt.Errorf("failed to parse best ask price: %w", err)
		}
		size, err := strconv.ParseFloat(mb.Asks[len(mb.Asks)-1].Size, 64)
		if err != nil {
			return fmt.Errorf("failed to parse best ask size: %w", err)
		}
		mb.BestAskParsed = ask
		mb.BestAskSizeParsed = size
	}
	
	// Parse timestamp
	ts, err := strconv.ParseInt(mb.Timestamp, 10, 64)
	if err != nil {
		return fmt.Errorf("failed to parse timestamp: %w", err)
	}
	mb.TimestampParsed = ts
	
	// Calculate total liquidity (sum of all bid and ask sizes)
	totalLiquidity := 0.0
	for _, bid := range mb.Bids {
		size, _ := strconv.ParseFloat(bid.Size, 64)
		totalLiquidity += size
	}
	for _, ask := range mb.Asks {
		size, _ := strconv.ParseFloat(ask.Size, 64)
		totalLiquidity += size
	}
	mb.LiquidityParsed = totalLiquidity
	
	return nil
}

// OrderRequest represents an order to place on Polymarket
type OrderRequest struct {
	MarketID      string  `json:"market_id"`
	Side          string  `json:"side"` // "BUY" or "SELL"
	Price         float64 `json:"price"`
	Size          float64 `json:"size"`
	OrderType     string  `json:"order_type"` // "LIMIT" or "MARKET"
	ClientOrderID string  `json:"client_order_id,omitempty"`
	ExpirationTime int64  `json:"expiration_time,omitempty"`
}

// OrderResponse represents a response from placing an order
type OrderResponse struct {
	OrderID       string    `json:"order_id"`
	ClientOrderID string    `json:"client_order_id"`
	Status        string    `json:"status"`
	Timestamp     int64     `json:"timestamp"`
	FilledSize    float64   `json:"filled_size"`
	RemainingSize float64   `json:"remaining_size"`
	AveragePrice  float64   `json:"average_price"`
}

// Position represents a current position in a market
type Position struct {
	MarketID string  `json:"market_id"`
	Symbol   string  `json:"symbol"`
	Side     string  `json:"side"` // "LONG" or "SHORT"
	Size     float64 `json:"size"`
	AvgPrice float64 `json:"avg_price"`
	PnL      float64 `json:"pnl"`
	PnLPct   float64 `json:"pnl_pct"`
}

// GetMarketBook fetches the current order book for a market using token ID
func (c *Client) GetMarketBook(tokenID string) (*MarketBook, error) {
	// CLOB API uses token_id parameter for the order book endpoint
	endpoint := fmt.Sprintf("%s/book?token_id=%s", c.baseURL, tokenID)
	
	req, err := http.NewRequest("GET", endpoint, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	c.setAuthHeaders(req)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API error: status %d, body: %s", resp.StatusCode, string(body))
	}

	var book MarketBook
	if err := json.NewDecoder(resp.Body).Decode(&book); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	// Parse the interface{} values to proper types
	if err := book.ParseBook(); err != nil {
		return nil, fmt.Errorf("failed to parse market book: %w", err)
	}

	return &book, nil
}

// PlaceOrder places an order on the market
func (c *Client) PlaceOrder(order *OrderRequest) (*OrderResponse, error) {
	endpoint := fmt.Sprintf("%s/orders", c.baseURL)

	body, err := json.Marshal(order)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal order: %w", err)
	}

	req, err := http.NewRequest("POST", endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	c.setAuthHeaders(req)
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API error: status %d, body: %s", resp.StatusCode, string(body))
	}

	var orderResp OrderResponse
	if err := json.NewDecoder(resp.Body).Decode(&orderResp); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &orderResp, nil
}

// CancelOrder cancels an existing order
func (c *Client) CancelOrder(orderID string) error {
	endpoint := fmt.Sprintf("%s/orders/%s", c.baseURL, orderID)

	req, err := http.NewRequest("DELETE", endpoint, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	c.setAuthHeaders(req)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusNoContent {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("API error: status %d, body: %s", resp.StatusCode, string(body))
	}

	return nil
}

// GetOpenOrders retrieves all open orders
func (c *Client) GetOpenOrders(marketID string) ([]OrderResponse, error) {
	endpoint := fmt.Sprintf("%s/orders?market_id=%s&status=OPEN", c.baseURL, marketID)

	req, err := http.NewRequest("GET", endpoint, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	c.setAuthHeaders(req)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API error: status %d, body: %s", resp.StatusCode, string(body))
	}

	var orders []OrderResponse
	if err := json.NewDecoder(resp.Body).Decode(&orders); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return orders, nil
}

// GetPositions retrieves all current positions
func (c *Client) GetPositions() ([]Position, error) {
	endpoint := fmt.Sprintf("%s/positions", c.baseURL)

	req, err := http.NewRequest("GET", endpoint, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	c.setAuthHeaders(req)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API error: status %d, body: %s", resp.StatusCode, string(body))
	}

	var positions []Position
	if err := json.NewDecoder(resp.Body).Decode(&positions); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return positions, nil
}

// setAuthHeaders sets authentication headers for requests
func (c *Client) setAuthHeaders(req *http.Request) {
	req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", c.apiKey))
	req.Header.Set("User-Agent", "Janus-Bot/1.0")
}
