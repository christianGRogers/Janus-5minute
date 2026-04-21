package polymarket

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// GammaClient handles Polymarket Gamma API calls for market discovery
type GammaClient struct {
	baseURL    string
	httpClient *http.Client
}

// NewGammaClient creates a new Gamma API client
func NewGammaClient(baseURL string) *GammaClient {
	return &GammaClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// MarketInfo represents market information from the Gamma API
type MarketInfo struct {
	ID              string `json:"id"`
	Slug            string `json:"slug"`
	Title           string `json:"title"`
	Description     string `json:"description"`
	Active          bool   `json:"active"`
	Closed          bool   `json:"closed"`
	ConditionID     string `json:"conditionId"`
	CLOBTokenIDsStr string `json:"clobTokenIds"` // This is a JSON string in the response
	CLOBTokenIDs    []string `json:"-"` // We'll parse it manually
	CreatedAt       string `json:"createdAt"`
	UpdatedAt       string `json:"updatedAt"`
	Volume          string `json:"volume"`
	Liquidity       string `json:"liquidity"`
	BestBid         float64 `json:"bestBid"`
	BestAsk         float64 `json:"bestAsk"`
}

// UnmarshalJSON custom unmarshaler to parse clobTokenIds from JSON string
func (m *MarketInfo) UnmarshalJSON(data []byte) error {
	type Alias MarketInfo
	aux := &struct {
		*Alias
	}{
		Alias: (*Alias)(m),
	}

	if err := json.Unmarshal(data, &aux); err != nil {
		return err
	}

	// Parse the clobTokenIds JSON string into a slice
	if m.CLOBTokenIDsStr != "" {
		var tokenIDs []string
		if err := json.Unmarshal([]byte(m.CLOBTokenIDsStr), &tokenIDs); err != nil {
			// If parsing fails, just leave it empty
			m.CLOBTokenIDs = []string{}
		} else {
			m.CLOBTokenIDs = tokenIDs
		}
	}

	return nil
}

// GetActiveMarketsWithSlug fetches markets matching a slug pattern
func (gc *GammaClient) GetActiveMarketsWithSlug(slug string) ([]MarketInfo, error) {
	endpoint := fmt.Sprintf("%s/markets?active=true&closed=false&slug=%s", gc.baseURL, slug)

	req, err := http.NewRequest("GET", endpoint, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("User-Agent", "Janus-Bot/1.0")

	resp, err := gc.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API error: status %d, body: %s", resp.StatusCode, string(body))
	}

	// Try to decode as array first (direct response)
	var markets []MarketInfo
	if err := json.NewDecoder(resp.Body).Decode(&markets); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return markets, nil
}

// GetAllActiveMarkets fetches all active markets
func (gc *GammaClient) GetAllActiveMarkets(limit int) ([]MarketInfo, error) {
	endpoint := fmt.Sprintf("%s/markets?active=true&closed=false&limit=%d", gc.baseURL, limit)

	req, err := http.NewRequest("GET", endpoint, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("User-Agent", "Janus-Bot/1.0")

	resp, err := gc.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API error: status %d, body: %s", resp.StatusCode, string(body))
	}

	// Try to decode as array first (direct response)
	var markets []MarketInfo
	if err := json.NewDecoder(resp.Body).Decode(&markets); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return markets, nil
}

// GetMarketBySlug fetches a single market by slug
func (gc *GammaClient) GetMarketBySlug(slug string) (*MarketInfo, error) {
	markets, err := gc.GetActiveMarketsWithSlug(slug)
	if err != nil {
		return nil, err
	}

	if len(markets) == 0 {
		return nil, fmt.Errorf("market not found: %s", slug)
	}

	return &markets[0], nil
}

// GetCurrentBTCUpDownMarket gets the current 5-minute BTC market
func (gc *GammaClient) GetCurrentBTCUpDownMarket() (*MarketInfo, error) {
	// Calculate current 5-minute window timestamp
	now := time.Now().Unix()
	windowTS := now - (now % 300) // Current window start (divisible by 300)

	slug := fmt.Sprintf("btc-updown-5m-%d", windowTS)
	return gc.GetMarketBySlug(slug)
}

// GetCurrentETHUpDownMarket gets the current 5-minute ETH market
func (gc *GammaClient) GetCurrentETHUpDownMarket() (*MarketInfo, error) {
	// Calculate current 5-minute window timestamp
	now := time.Now().Unix()
	windowTS := now - (now % 300) // Current window start (divisible by 300)

	slug := fmt.Sprintf("eth-updown-5m-%d", windowTS)
	return gc.GetMarketBySlug(slug)
}

// GetCurrentUpDownMarket gets the current 5-minute market for a given crypto
func (gc *GammaClient) GetCurrentUpDownMarket(crypto string) (*MarketInfo, error) {
	// Calculate current 5-minute window timestamp
	now := time.Now().Unix()
	windowTS := now - (now % 300) // Current window start (divisible by 300)

	slug := fmt.Sprintf("%s-updown-5m-%d", crypto, windowTS)
	return gc.GetMarketBySlug(slug)
}

// FindFiveMinuteMarkets finds all 5-minute Up/Down markets by querying specific cryptos
func (gc *GammaClient) FindFiveMinuteMarkets() (map[string]*MarketInfo, error) {
	fiveMinMarkets := make(map[string]*MarketInfo)

	// Start with just BTC, can add more later
	cryptos := []string{"btc"}

	// Calculate current 5-minute window timestamp
	now := time.Now().Unix()
	windowTS := now - (now % 300) // Current window start (divisible by 300)

	for _, crypto := range cryptos {
		slug := fmt.Sprintf("%s-updown-5m-%d", crypto, windowTS)
		market, err := gc.GetMarketBySlug(slug)
		if err == nil && market != nil {
			fiveMinMarkets[market.Slug] = market
		}
		// Silently continue if market doesn't exist for this crypto
	}

	return fiveMinMarkets, nil
}
