package trading

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"sync"
	"time"
)

// ClosedPosition represents a closed position from the Polymarket API
type ClosedPosition struct {
	ProxyWallet     string  `json:"proxyWallet"`
	Asset           string  `json:"asset"`
	ConditionID     string  `json:"conditionId"`
	AvgPrice        float64 `json:"avgPrice"`
	TotalBought     float64 `json:"totalBought"`
	RealizedPnl     float64 `json:"realizedPnl"`
	CurPrice        float64 `json:"curPrice"`
	Timestamp       int64   `json:"timestamp"`
	Title           string  `json:"title"`
	Slug            string  `json:"slug"`
	Icon            string  `json:"icon"`
	EventSlug       string  `json:"eventSlug"`
	Outcome         string  `json:"outcome"`
	OutcomeIndex    int     `json:"outcomeIndex"`
	OppositeOutcome string  `json:"oppositeOutcome"`
	OppositeAsset   string  `json:"oppositeAsset"`
	EndDate         string  `json:"endDate"`
}

// LossCooldown tracks when a market had a losing trade and applies risk reduction
type LossCooldown struct {
	MarketTitle     string    // Market title (e.g., "Bitcoin Up or Down - May 29, 11:05PM-11:10PM ET")
	LossTime        time.Time // When the loss occurred
	CooldownEndTime time.Time // When the cooldown expires (3 hours later)
	RiskMultiplier  float64   // Reduced position size multiplier (0.5 = 50% of normal)
	LossPnL         float64   // Actual P&L from the loss
}

// MarketCheckQueue holds markets queued for loss checking
type MarketCheckQueue struct {
	Markets []string  // List of market slugs to check for losses
	mu      sync.Mutex
}

// LossTracker monitors closed positions and applies cooldowns to markets with losses
type LossTracker struct {
	userAddress        string                     // Polymarket user address (0x-prefixed)
	dataAPIEndpoint    string                     // Data API endpoint (e.g., https://data-api.polymarket.com)
	cooldowns          map[string]*LossCooldown   // Map of market title -> loss cooldown
	mu                 sync.RWMutex               // Thread-safe access
	lastCheckTime      time.Time                  // When we last polled the API
	minCheckInterval   time.Duration              // Minimum time between API polls (e.g., 5 minutes)
	cooldownDuration   time.Duration              // How long a cooldown lasts (e.g., 3 hours)
	lossPnlThreshold   float64                    // Only trigger cooldown if loss exceeds this (e.g., 0.5 = 50% loss)
	httpClient         *http.Client               // HTTP client for API calls
	marketQueue        *MarketCheckQueue          // Queue of markets to check (market N queued when N+1 starts)
}

// NewLossTracker creates a new loss tracker
func NewLossTracker(userAddress, dataAPIEndpoint string) *LossTracker {
	return &LossTracker{
		userAddress:      userAddress,
		dataAPIEndpoint:  dataAPIEndpoint,
		cooldowns:        make(map[string]*LossCooldown),
		lastCheckTime:    time.Now().Add(-10 * time.Minute), // Allow immediate first check
		minCheckInterval: 5 * time.Minute,                    // Poll at most every 5 minutes
		cooldownDuration: 3 * time.Hour,                      // Cooldown lasts 3 hours
		lossPnlThreshold: 0.5,                                // Loss >= 0.5 USDC triggers cooldown
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
		marketQueue: &MarketCheckQueue{
			Markets: make([]string, 0),
		},
	}
}

// CheckForNewLosses polls the Polymarket API for newly closed positions with losses
// Returns true if new losses were detected
func (lt *LossTracker) CheckForNewLosses() (bool, error) {
	// Rate limit: don't check more than once per minCheckInterval
	if time.Since(lt.lastCheckTime) < lt.minCheckInterval {
		return false, nil
	}

	lt.lastCheckTime = time.Now()

	// Clean up expired cooldowns
	lt.cleanupExpiredCooldowns()

	// Call Polymarket API to get closed positions
	positions, err := lt.fetchClosedPositions()
	if err != nil {
		log.Printf("[LossTracker] Error fetching closed positions: %v", err)
		return false, err
	}

	newLosses := false

	// Check each position for losses
	for _, pos := range positions {
		// Only track losses
		if pos.RealizedPnl >= 0 {
			continue
		}

		// Only trigger cooldown if loss exceeds threshold
		if pos.RealizedPnl > -lt.lossPnlThreshold {
			log.Printf("[LossTracker] Loss detected for %s: %.4f USDC (below threshold of %.4f), ignoring", pos.Title, pos.RealizedPnl, lt.lossPnlThreshold)
			continue
		}

		// Check if we already have a cooldown for this market
		lt.mu.RLock()
		existingCooldown, exists := lt.cooldowns[pos.Title]
		lt.mu.RUnlock()

		if exists {
			// Update cooldown end time if new loss is more recent
			if pos.Timestamp > existingCooldown.LossTime.Unix() {
				lt.mu.Lock()
				lt.cooldowns[pos.Title] = &LossCooldown{
					MarketTitle:     pos.Title,
					LossTime:        time.Unix(pos.Timestamp, 0),
					CooldownEndTime: time.Unix(pos.Timestamp, 0).Add(lt.cooldownDuration),
					RiskMultiplier:  0.5, // Apply 50% risk reduction
					LossPnL:         pos.RealizedPnl,
				}
				lt.mu.Unlock()
				log.Printf("[LossTracker] Loss cooldown renewed for %s: %.4f USDC loss, risk multiplier: 0.5x for 3h", pos.Title, pos.RealizedPnl)
				newLosses = true
			}
		} else {
			// New loss detected
			lt.mu.Lock()
			lt.cooldowns[pos.Title] = &LossCooldown{
				MarketTitle:     pos.Title,
				LossTime:        time.Unix(pos.Timestamp, 0),
				CooldownEndTime: time.Unix(pos.Timestamp, 0).Add(lt.cooldownDuration),
				RiskMultiplier:  0.5, // Apply 50% risk reduction
				LossPnL:         pos.RealizedPnl,
			}
			lt.mu.Unlock()
			log.Printf("[LossTracker] NEW LOSS DETECTED: %s -> %.4f USDC loss, applying 0.5x risk multiplier for 3h", pos.Title, pos.RealizedPnl)
			newLosses = true
		}
	}

	return newLosses, nil
}

// GetRiskMultiplier returns the risk multiplier for a market title (1.0 = normal, 0.5 = reduced)
// Returns 0.5 if market is in cooldown, otherwise 1.0
func (lt *LossTracker) GetRiskMultiplier(marketTitle string) float64 {
	lt.mu.RLock()
	defer lt.mu.RUnlock()

	cooldown, exists := lt.cooldowns[marketTitle]
	if !exists {
		return 1.0
	}

	// Check if cooldown has expired
	if time.Now().After(cooldown.CooldownEndTime) {
		return 1.0
	}

	return cooldown.RiskMultiplier
}

// GetActiveCooldowns returns a snapshot of all active cooldowns
func (lt *LossTracker) GetActiveCooldowns() map[string]*LossCooldown {
	lt.mu.RLock()
	defer lt.mu.RUnlock()

	result := make(map[string]*LossCooldown)
	now := time.Now()

	for title, cooldown := range lt.cooldowns {
		if now.Before(cooldown.CooldownEndTime) {
			result[title] = cooldown
		}
	}

	return result
}

// fetchClosedPositions calls the Polymarket Data API to get closed positions for this user
func (lt *LossTracker) fetchClosedPositions() ([]*ClosedPosition, error) {
	// Construct URL with query parameters
	url := fmt.Sprintf("%s/closed-positions?user=%s&limit=50&sortBy=TIMESTAMP&sortDirection=DESC",
		lt.dataAPIEndpoint, lt.userAddress)

	log.Printf("[LossTracker] Fetching closed positions from: %s", url)

	resp, err := lt.httpClient.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to fetch closed positions: %w", err)
	}
	defer resp.Body.Close()

	// Check for HTTP errors
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(body))
	}

	// Parse response
	var positions []*ClosedPosition
	if err := json.NewDecoder(resp.Body).Decode(&positions); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	log.Printf("[LossTracker] Fetched %d closed positions", len(positions))
	return positions, nil
}

// cleanupExpiredCooldowns removes cooldowns that have expired
func (lt *LossTracker) cleanupExpiredCooldowns() {
	lt.mu.Lock()
	defer lt.mu.Unlock()

	now := time.Now()
	expiredMarkets := []string{}

	for title, cooldown := range lt.cooldowns {
		if now.After(cooldown.CooldownEndTime) {
			expiredMarkets = append(expiredMarkets, title)
		}
	}

	for _, title := range expiredMarkets {
		delete(lt.cooldowns, title)
		log.Printf("[LossTracker] Cooldown expired for: %s", title)
	}
}

// QueueMarketForLossCheck adds a market slug to the check queue
// This is called when market N starts, queuing market N for checking when N+1 starts
// The market will be checked 5 minutes (one full window) after it closes
func (lt *LossTracker) QueueMarketForLossCheck(marketSlug string) {
	lt.marketQueue.mu.Lock()
	defer lt.marketQueue.mu.Unlock()
	
	lt.marketQueue.Markets = append(lt.marketQueue.Markets, marketSlug)
	log.Printf("[LossTracker] Queued market %s for loss check (will check in next window)", marketSlug)
}

// GetQueuedMarkets returns and clears the market queue
// Called during OnMarketWindowChange to get all markets that need checking
func (lt *LossTracker) GetQueuedMarkets() []string {
	lt.marketQueue.mu.Lock()
	defer lt.marketQueue.mu.Unlock()
	
	markets := lt.marketQueue.Markets
	lt.marketQueue.Markets = make([]string, 0)  // Clear queue
	
	if len(markets) > 0 {
		log.Printf("[LossTracker] Processing market check queue: %d markets", len(markets))
	}
	
	return markets
}

// FilterByMarketTitle extracts market title and checks for cooldown match
// Matches titles that contain the provided filter string
func FilterByMarketTitle(fullTitle, filterPattern string) bool {
	return strings.Contains(strings.ToLower(fullTitle), strings.ToLower(filterPattern))
}
