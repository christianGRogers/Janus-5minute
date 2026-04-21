package market

import (
	"fmt"
	"strings"
	"sync"
	"time"

	"janus-bot/config"
	"janus-bot/pkg/polymarket"
)

// MarketDataCache holds recent market data for all tracked markets
type MarketDataCache struct {
	mu   sync.RWMutex
	data map[string]*polymarket.MarketBook
}

// MarketMetadata holds metadata about discovered markets
type MarketMetadata struct {
	ID           string
	ConditionID  string
	CLOBTokenIDs []string
}

// MarketFetcher continuously fetches market data from Polymarket
type MarketFetcher struct {
	client              *polymarket.Client
	gammaClient         *polymarket.GammaClient
	config              *config.PolymarketConfig
	cache               *MarketDataCache
	marketMetadata      map[string]*MarketMetadata // Maps market slug to metadata
	marketDiscoveryTime map[string]int64           // Tracks when each market was discovered
	metadataMutex       sync.RWMutex
	stopChan            chan struct{}
	stoppedChan         chan struct{}
	errorHandler        func(error)
	pollInterval        time.Duration
	discoveryInterval   time.Duration
	lastFetchTimestamp  map[string]int64
	fetchMutex          sync.RWMutex
	lastDiscoveryTime   time.Time
	maxMarketAge        int64 // Maximum age of a market in seconds before it's considered expired
}

// NewMarketFetcher creates a new market data fetcher
func NewMarketFetcher(client *polymarket.Client, cfg *config.PolymarketConfig) *MarketFetcher {
	gammaClient := polymarket.NewGammaClient("https://gamma-api.polymarket.com")

	return &MarketFetcher{
		client:              client,
		gammaClient:         gammaClient,
		config:              cfg,
		cache:               &MarketDataCache{data: make(map[string]*polymarket.MarketBook)},
		marketMetadata:      make(map[string]*MarketMetadata),
		marketDiscoveryTime: make(map[string]int64),
		stopChan:            make(chan struct{}),
		stoppedChan:         make(chan struct{}),
		pollInterval:        time.Duration(cfg.PollIntervalSeconds) * time.Second,
		discoveryInterval:   5 * time.Minute, // Discover new markets every 5 minutes (when new ones become active)
		lastFetchTimestamp:  make(map[string]int64),
		lastDiscoveryTime:   time.Now(),
		maxMarketAge:        600, // Markets older than 10 minutes are considered expired (2 market cycles)
		errorHandler: func(err error) {
			// Default error handler - can be overridden
			fmt.Printf("Market fetcher error: %v\n", err)
		},
	}
}

// SetErrorHandler sets a custom error handler
func (mf *MarketFetcher) SetErrorHandler(handler func(error)) {
	mf.errorHandler = handler
}

// Start begins polling market data
func (mf *MarketFetcher) Start() {
	go mf.run()
}

// Stop halts the polling loop
func (mf *MarketFetcher) Stop() {
	close(mf.stopChan)
	<-mf.stoppedChan
}

// run is the main polling loop
func (mf *MarketFetcher) run() {
	ticker := time.NewTicker(mf.pollInterval)
	defer ticker.Stop()

	defer close(mf.stoppedChan)

	// Initial discovery
	mf.discoverMarkets()

	// Fetch immediately on start
	mf.fetchAll()

	lastDiscoveryWindow := int64(-1)

	for {
		select {
		case <-mf.stopChan:
			return
		case <-ticker.C:
			// Check if we've crossed a 5-minute market boundary
			now := time.Now().Unix()
			currentWindow := now / 300 // Market windows are 300-second (5-minute) intervals

			if currentWindow != lastDiscoveryWindow {
				// Market window has changed - discover new markets
				mf.discoverMarkets()
				lastDiscoveryWindow = currentWindow
			}

			// Fetch market data
			mf.fetchAll()
		}
	}
}

// discoverMarkets discovers and updates available 5-minute markets
func (mf *MarketFetcher) discoverMarkets() {
	// Discover 5-minute markets
	fiveMinMarkets, err := mf.gammaClient.FindFiveMinuteMarkets()
	if err != nil {
		mf.errorHandler(fmt.Errorf("failed to discover markets: %w", err))
		return
	}

	mf.metadataMutex.Lock()
	defer mf.metadataMutex.Unlock()

	now := time.Now().Unix()
	
	// Remove all old markets that are not in the current discovery set
	// This ensures we only keep the latest market window
	removedMarkets := []string{}
	for slug := range mf.marketMetadata {
		if _, exists := fiveMinMarkets[slug]; !exists {
			// Market is not in current discovery - it's old, remove it
			removedMarkets = append(removedMarkets, slug)
			delete(mf.marketMetadata, slug)
			delete(mf.marketDiscoveryTime, slug)
			
			// Also clean up cache entries for this market
			mf.cache.mu.Lock()
			for key := range mf.cache.data {
				if strings.HasPrefix(key, slug) {
					delete(mf.cache.data, key)
				}
			}
			mf.cache.mu.Unlock()
		}
	}

	// Add or update discovered markets
	newMarkets := []string{}
	for slug, market := range fiveMinMarkets {
		if market != nil {
			// Check if this is a new market
			if _, exists := mf.marketMetadata[slug]; !exists {
				newMarkets = append(newMarkets, slug)
			}

			mf.marketMetadata[slug] = &MarketMetadata{
				ID:           market.ID,
				ConditionID:  market.ConditionID,
				CLOBTokenIDs: market.CLOBTokenIDs,
			}
			mf.marketDiscoveryTime[slug] = now
		}
	}

	// Log market changes
	if len(newMarkets) > 0 {
		mf.errorHandler(fmt.Errorf("🆕 NEW MARKETS DISCOVERED: %s", strings.Join(newMarkets, ", ")))
	}
	if len(removedMarkets) > 0 {
		mf.errorHandler(fmt.Errorf("⏰ OLD MARKETS REMOVED: %s", strings.Join(removedMarkets, ", ")))
	}

	currentCount := len(mf.marketMetadata)
	mf.errorHandler(fmt.Errorf("📊 Active markets: %d", currentCount))

	mf.lastDiscoveryTime = time.Now()
}

// fetchAll fetches data for all configured markets concurrently
func (mf *MarketFetcher) fetchAll() {
	var wg sync.WaitGroup

	// Fetch data for all discovered markets
	mf.metadataMutex.RLock()
	for slug, metadata := range mf.marketMetadata {
		// Fetch both UP and DOWN outcomes
		if len(metadata.CLOBTokenIDs) >= 2 {
			// UP outcome (first token)
			wg.Add(1)
			go func(s string, tokenID string, outcome string) {
				defer wg.Done()
				mf.fetchMarket(s, tokenID, outcome)
			}(slug, metadata.CLOBTokenIDs[0], "UP")
			
			// DOWN outcome (second token)
			wg.Add(1)
			go func(s string, tokenID string, outcome string) {
				defer wg.Done()
				mf.fetchMarket(s, tokenID, outcome)
			}(slug, metadata.CLOBTokenIDs[1], "DOWN")
		}
	}
	mf.metadataMutex.RUnlock()

	wg.Wait()
}

// fetchMarket fetches data for a specific market outcome
func (mf *MarketFetcher) fetchMarket(slug string, tokenID string, outcome string) {
	// Create a cache key that includes the outcome
	cacheKey := fmt.Sprintf("%s-%s", slug, outcome)

	// Fetch using the CLOB token ID
	book, err := mf.client.GetMarketBook(tokenID)
	if err != nil {
		mf.errorHandler(fmt.Errorf("failed to fetch market %s (%s) (token: %s): %w", slug, outcome, tokenID, err))
		return
	}

	mf.cache.mu.Lock()
	defer mf.cache.mu.Unlock()

	// Cache by slug-outcome combination
	mf.cache.data[cacheKey] = book

	mf.fetchMutex.Lock()
	mf.lastFetchTimestamp[cacheKey] = time.Now().Unix()
	mf.fetchMutex.Unlock()
}

// GetLatestBook returns the latest order book for a market
func (mf *MarketFetcher) GetLatestBook(marketID string) (*polymarket.MarketBook, error) {
	mf.cache.mu.RLock()
	defer mf.cache.mu.RUnlock()

	book, exists := mf.cache.data[marketID]
	if !exists {
		return nil, fmt.Errorf("no data available for market: %s", marketID)
	}

	return book, nil
}

// GetAllLatestBooks returns the latest order books for all configured markets
func (mf *MarketFetcher) GetAllLatestBooks() map[string]*polymarket.MarketBook {
	mf.cache.mu.RLock()
	defer mf.cache.mu.RUnlock()

	// Return a copy
	booksCopy := make(map[string]*polymarket.MarketBook)
	for k, v := range mf.cache.data {
		booksCopy[k] = v
	}
	return booksCopy
}

// GetDiscoveredMarkets returns all currently discovered market slugs
func (mf *MarketFetcher) GetDiscoveredMarkets() []string {
	mf.metadataMutex.RLock()
	defer mf.metadataMutex.RUnlock()

	markets := make([]string, 0, len(mf.marketMetadata))
	for slug := range mf.marketMetadata {
		markets = append(markets, slug)
	}
	return markets
}

// GetMarketMetadata returns metadata for a specific market
func (mf *MarketFetcher) GetMarketMetadata(slug string) (*MarketMetadata, bool) {
	mf.metadataMutex.RLock()
	defer mf.metadataMutex.RUnlock()

	meta, exists := mf.marketMetadata[slug]
	return meta, exists
}

// GetLastFetchTime returns the timestamp of the last successful fetch for a market
func (mf *MarketFetcher) GetLastFetchTime(marketID string) (int64, bool) {
	mf.fetchMutex.RLock()
	defer mf.fetchMutex.RUnlock()

	ts, exists := mf.lastFetchTimestamp[marketID]
	return ts, exists
}

// IsFresh checks if market data is fresh (within the poll interval + buffer)
func (mf *MarketFetcher) IsFresh(marketID string, maxAgeSeconds int64) bool {
	lastFetch, exists := mf.GetLastFetchTime(marketID)
	if !exists {
		return false
	}

	return (time.Now().Unix() - lastFetch) <= maxAgeSeconds
}
