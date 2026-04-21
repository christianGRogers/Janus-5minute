package trading

import (
	"fmt"
	"sync"
	"time"
)

// PaperTrade represents a simulated trade
type PaperTrade struct {
	OrderID       string
	MarketID      string
	Side          string  // "BUY" or "SELL"
	Price         float64
	Size          float64
	Status        string    // "OPEN", "FILLED", "CANCELLED"
	FilledSize    float64
	Timestamp     int64
	ExpirationTime int64
}

// PaperPosition represents a simulated position
type PaperPosition struct {
	MarketID  string
	Symbol    string
	Side      string
	Size      float64
	AvgPrice  float64
	EntryTime int64
}

// PaperTradingEngine simulates trading without placing actual orders
type PaperTradingEngine struct {
	mu              sync.RWMutex
	balance         float64
	positions       map[string]*PaperPosition
	trades          map[string]*PaperTrade
	tradeHistory    []*PaperTrade
	orderIDCounter  int64
	startingBalance float64
}

// NewPaperTradingEngine creates a new paper trading engine
func NewPaperTradingEngine(startingBalance float64) *PaperTradingEngine {
	return &PaperTradingEngine{
		balance:         startingBalance,
		startingBalance: startingBalance,
		positions:       make(map[string]*PaperPosition),
		trades:          make(map[string]*PaperTrade),
		tradeHistory:    make([]*PaperTrade, 0),
		orderIDCounter:  1000,
	}
}

// PlaceOrder simulates placing an order
func (p *PaperTradingEngine) PlaceOrder(marketID string, side string, price float64, size float64) (string, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	// Check if we have sufficient balance for a buy order
	requiredBalance := price * size
	if side == "BUY" && requiredBalance > p.balance {
		return "", fmt.Errorf("insufficient balance: required %.2f USDC, have %.2f USDC", requiredBalance, p.balance)
	}

	p.orderIDCounter++
	orderID := fmt.Sprintf("PAPER-%d", p.orderIDCounter)

	trade := &PaperTrade{
		OrderID:    orderID,
		MarketID:   marketID,
		Side:       side,
		Price:      price,
		Size:       size,
		Status:     "FILLED",
		FilledSize: size,
		Timestamp:  time.Now().Unix(),
	}

	p.trades[orderID] = trade
	p.tradeHistory = append(p.tradeHistory, trade)

	// Update balance
	if side == "BUY" {
		p.balance -= requiredBalance
	} else {
		p.balance += requiredBalance
	}

	// Update position
	posKey := marketID
	if pos, exists := p.positions[posKey]; exists {
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
					delete(p.positions, posKey)
				}
			} else {
				remainingSize := size - pos.Size
				delete(p.positions, posKey)
				p.positions[posKey] = &PaperPosition{
					MarketID:  marketID,
					Side:       side,
					Size:       remainingSize,
					AvgPrice:  price,
					EntryTime: time.Now().Unix(),
				}
			}
		}
	} else {
		// New position
		p.positions[posKey] = &PaperPosition{
			MarketID:  marketID,
			Side:       side,
			Size:       size,
			AvgPrice:  price,
			EntryTime: time.Now().Unix(),
		}
	}

	return orderID, nil
}

// CancelOrder simulates cancelling an order
func (p *PaperTradingEngine) CancelOrder(orderID string) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	trade, exists := p.trades[orderID]
	if !exists {
		return fmt.Errorf("order not found: %s", orderID)
	}

	if trade.Status != "OPEN" {
		return fmt.Errorf("cannot cancel order with status: %s", trade.Status)
	}

	trade.Status = "CANCELLED"
	return nil
}

// GetPositions returns all current positions
func (p *PaperTradingEngine) GetPositions() map[string]*PaperPosition {
	p.mu.RLock()
	defer p.mu.RUnlock()

	// Return a copy to prevent external modifications
	posCopy := make(map[string]*PaperPosition)
	for k, v := range p.positions {
		posCopy[k] = v
	}
	return posCopy
}

// GetBalance returns current balance
func (p *PaperTradingEngine) GetBalance() float64 {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.balance
}

// GetEquity returns total account equity (balance + positions value at current price)
func (p *PaperTradingEngine) GetEquity(currentPrices map[string]float64) float64 {
	p.mu.RLock()
	defer p.mu.RUnlock()

	equity := p.balance
	for marketID, pos := range p.positions {
		if price, exists := currentPrices[marketID]; exists {
			equity += pos.Size * price
		}
	}
	return equity
}

// GetROI returns the return on investment percentage
func (p *PaperTradingEngine) GetROI(currentPrices map[string]float64) float64 {
	equity := p.GetEquity(currentPrices)
	if p.startingBalance == 0 {
		return 0
	}
	return ((equity - p.startingBalance) / p.startingBalance) * 100
}

// GetTradeHistory returns all trades (simulated and real)
func (p *PaperTradingEngine) GetTradeHistory() []*PaperTrade {
	p.mu.RLock()
	defer p.mu.RUnlock()

	// Return a copy
	historyCopy := make([]*PaperTrade, len(p.tradeHistory))
	copy(historyCopy, p.tradeHistory)
	return historyCopy
}
