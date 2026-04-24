package trading

import (
	"fmt"
	"sync"
	"time"
)

// Polymarket taker fee formula: fee = C × 0.072020 × p × (1 - p)
// where C is the size (number of shares), p is the price
const TAKER_FEE_COEFFICIENT = 0.072020

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
	Side      string  // "BUY" or "SELL"
	Direction string // "UP" or "DOWN" (based on market slug)
	Size      float64
	AvgPrice  float64
	EntryTime int64
}

// ClosedPosition represents a position that was closed with P&L
type ClosedPosition struct {
	MarketID    string
	Outcome     string
	EntryPrice  float64
	ExitPrice   float64
	Size        float64
	ProfitLoss  float64
	EntryFee    float64 // Fee paid when entering
	ExitFee     float64 // Fee paid when exiting
	NetProfitLoss float64 // ProfitLoss minus fees
	ProfitPct   float64
	EntryTime   int64
	ExitTime    int64
}

// PaperTradingEngine simulates trading without placing actual orders
type PaperTradingEngine struct {
	mu              sync.RWMutex
	balance         float64
	positions       map[string]*PaperPosition
	closedPositions []*ClosedPosition // Track closed positions for P&L reporting
	cumulativeProfit float64 // Total profit from all closed positions
	trades          map[string]*PaperTrade
	tradeHistory    []*PaperTrade
	orderIDCounter  int64
	startingBalance float64
}

// calculateTakerFee calculates the taker fee using Polymarket formula
// fee = C × 0.072020 × p × (1 - p)
// where C is the size and p is the price
func calculateTakerFee(size float64, price float64) float64 {
	return size * TAKER_FEE_COEFFICIENT * price * (1 - price)
}

// NewPaperTradingEngine creates a new paper trading engine
func NewPaperTradingEngine(startingBalance float64) *PaperTradingEngine {
	return &PaperTradingEngine{
		balance:         startingBalance,
		startingBalance: startingBalance,
		positions:       make(map[string]*PaperPosition),
		closedPositions: make([]*ClosedPosition, 0),
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
	// Extract direction from market slug (e.g., "btc-updown-5m-XXXXX-UP" or "btc-updown-5m-XXXXX-DOWN")
	direction := "UP"
	if len(marketID) > 3 && marketID[len(marketID)-4:] == "DOWN" {
		direction = "DOWN"
	}
	
	if pos, exists := p.positions[posKey]; exists {
		if pos.Side == side {
			// Increase position
			totalCost := pos.AvgPrice*pos.Size + price*size
			pos.Size += size
			pos.AvgPrice = totalCost / pos.Size
		} else {
			// Close or reduce position
			if pos.Size >= size {
				// Record closed position with P&L
				closedPos := &ClosedPosition{
					MarketID:   marketID,
					Outcome:    pos.Direction,
					EntryPrice: pos.AvgPrice,
					ExitPrice:  price,
					Size:       size,
					EntryTime:  pos.EntryTime,
					ExitTime:   time.Now().Unix(),
				}
				// Calculate P&L
				if pos.Side == "BUY" {
					closedPos.ProfitLoss = (price - pos.AvgPrice) * size
				} else {
					closedPos.ProfitLoss = (pos.AvgPrice - price) * size
				}
				closedPos.ProfitPct = (closedPos.ProfitLoss / (pos.AvgPrice * size)) * 100
				p.closedPositions = append(p.closedPositions, closedPos)
				p.cumulativeProfit += closedPos.ProfitLoss

				pos.Size -= size
				if pos.Size == 0 {
					delete(p.positions, posKey)
				}
			} else {
				remainingSize := size - pos.Size
				// Record closed position with remaining size
				closedPos := &ClosedPosition{
					MarketID:   marketID,
					Outcome:    pos.Direction,
					EntryPrice: pos.AvgPrice,
					ExitPrice:  price,
					Size:       pos.Size,
					EntryTime:  pos.EntryTime,
					ExitTime:   time.Now().Unix(),
				}
				if pos.Side == "BUY" {
					closedPos.ProfitLoss = (price - pos.AvgPrice) * pos.Size
				} else {
					closedPos.ProfitLoss = (pos.AvgPrice - price) * pos.Size
				}
				closedPos.ProfitPct = (closedPos.ProfitLoss / (pos.AvgPrice * pos.Size)) * 100
				p.closedPositions = append(p.closedPositions, closedPos)
				p.cumulativeProfit += closedPos.ProfitLoss

				delete(p.positions, posKey)
				p.positions[posKey] = &PaperPosition{
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
		p.positions[posKey] = &PaperPosition{
			MarketID:  marketID,
			Side:      side,
			Direction: direction,
			Size:      size,
			AvgPrice:  price,
			EntryTime: time.Now().Unix(),
		}
	}

	return orderID, nil
}

// PlaceOrderWithDelay simulates placing an order with realistic network/execution delay
// Delay ranges from 100-500ms to simulate real-world conditions
func (p *PaperTradingEngine) PlaceOrderWithDelay(marketID string, side string, price float64, size float64) (string, error) {
	// Simulate realistic order execution delay
	// Typical exchange response times: 100-500ms
	delay := time.Duration(100 + (time.Now().UnixNano() % 400)) * time.Millisecond
	time.Sleep(delay)
	
	return p.PlaceOrder(marketID, side, price, size)
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

// CloseMarketPositions closes all positions for a given market at a specific exit price
// Returns closed positions and their P&L (after fees)
func (p *PaperTradingEngine) CloseMarketPositions(marketID string, exitPrice float64) []*ClosedPosition {
	p.mu.Lock()
	defer p.mu.Unlock()

	var closedPos []*ClosedPosition

	if pos, exists := p.positions[marketID]; exists {
		// Calculate entry and exit fees using Polymarket formula
		entryFee := calculateTakerFee(pos.Size, pos.AvgPrice)
		exitFee := calculateTakerFee(pos.Size, exitPrice)
		totalFees := entryFee + exitFee

		// Record closed position
		closed := &ClosedPosition{
			MarketID:   marketID,
			Outcome:    pos.Direction,
			EntryPrice: pos.AvgPrice,
			ExitPrice:  exitPrice,
			Size:       pos.Size,
			EntryTime:  pos.EntryTime,
			ExitTime:   time.Now().Unix(),
			EntryFee:   entryFee,
			ExitFee:    exitFee,
		}

		// Calculate P&L before fees
		if pos.Side == "BUY" {
			closed.ProfitLoss = (exitPrice - pos.AvgPrice) * pos.Size
		} else {
			closed.ProfitLoss = (pos.AvgPrice - exitPrice) * pos.Size
		}

		// Calculate net P&L after fees
		closed.NetProfitLoss = closed.ProfitLoss - totalFees
		closed.ProfitPct = (closed.NetProfitLoss / (pos.AvgPrice * pos.Size)) * 100

		p.closedPositions = append(p.closedPositions, closed)
		closedPos = append(closedPos, closed)
		p.cumulativeProfit += closed.NetProfitLoss

		// Update balance with net P&L
		p.balance += closed.NetProfitLoss

		// Remove position
		delete(p.positions, marketID)
	}

	return closedPos
}

// GetClosedPositions returns all closed positions
func (p *PaperTradingEngine) GetClosedPositions() []*ClosedPosition {
	p.mu.RLock()
	defer p.mu.RUnlock()

	// Return a copy
	closedCopy := make([]*ClosedPosition, len(p.closedPositions))
	copy(closedCopy, p.closedPositions)
	return closedCopy
}

// GetRecentClosedPositions returns closed positions from the last N trades
func (p *PaperTradingEngine) GetRecentClosedPositions(count int) []*ClosedPosition {
	p.mu.RLock()
	defer p.mu.RUnlock()

	if len(p.closedPositions) == 0 {
		return []*ClosedPosition{}
	}

	start := len(p.closedPositions) - count
	if start < 0 {
		start = 0
	}

	closedCopy := make([]*ClosedPosition, len(p.closedPositions[start:]))
	copy(closedCopy, p.closedPositions[start:])
	return closedCopy
}

// GetCumulativeProfit returns total profit from all closed positions
func (p *PaperTradingEngine) GetCumulativeProfit() float64 {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.cumulativeProfit
}
