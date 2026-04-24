package analytics

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// MarketPerformanceLog contains all metrics for a closed market window
type MarketPerformanceLog struct {
	// Market identification
	MarketID      string    `json:"market_id"`
	Timestamp     time.Time `json:"timestamp"`
	TimestampUnix int64     `json:"timestamp_unix"`

	// Market window info
	WindowStartTime int64 `json:"window_start_time"`
	WindowEndTime   int64 `json:"window_end_time"`
	WindowDuration  int   `json:"window_duration_seconds"`

	// Trading activity
	PositionCount    int     `json:"position_count"`
	CorrectPositions int     `json:"correct_positions"`
	WrongPositions   int     `json:"wrong_positions"`
	WinRate          float64 `json:"win_rate_percent"`

	// P&L metrics
	GrossProfit     float64 `json:"gross_profit_usdc"`
	TotalFees       float64 `json:"total_fees_usdc"`
	NetProfit       float64 `json:"net_profit_usdc"`
	AverageProfitPct float64 `json:"average_profit_percent"`

	// Entry/Exit details
	AvgEntryPrice   float64 `json:"avg_entry_price"`
	AvgExitPrice    float64 `json:"avg_exit_price"`
	TotalSizeTraded float64 `json:"total_size_traded_shares"`

	// Market conditions at resolution
	FinalUpPrice   float64 `json:"final_up_price"`
	FinalDownPrice float64 `json:"final_down_price"`
	Resolution     string  `json:"resolution"` // "UP" or "DOWN"

	// Account state
	AccountBalance  float64 `json:"account_balance_usdc"`
	AccountEquity   float64 `json:"account_equity_usdc"`
	CumulativeProfit float64 `json:"cumulative_profit_usdc"`
}

// MarketLogger handles logging market performance to files
type MarketLogger struct {
	mu            sync.Mutex
	logDir        string
	jsonFile      *os.File
	csvFile       *os.File
	csvWriter     *csv.Writer
	sessionID     string
}

// NewMarketLogger creates a new market logger
func NewMarketLogger(baseLogDir string) (*MarketLogger, error) {
	// Create log directory if it doesn't exist
	logDir := filepath.Join(baseLogDir, "logs", "markets")
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create log directory: %w", err)
	}

	// Session ID based on current timestamp
	sessionID := time.Now().Format("2006-01-02_15-04-05")
	sessionDir := filepath.Join(logDir, sessionID)
	if err := os.MkdirAll(sessionDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create session directory: %w", err)
	}

	ml := &MarketLogger{
		logDir:    sessionDir,
		sessionID: sessionID,
	}

	// Initialize JSON file
	jsonPath := filepath.Join(sessionDir, "market_performance.jsonl")
	jsonFile, err := os.Create(jsonPath)
	if err != nil {
		return nil, fmt.Errorf("failed to create JSON log file: %w", err)
	}
	ml.jsonFile = jsonFile

	// Initialize CSV file with headers
	csvPath := filepath.Join(sessionDir, "market_performance.csv")
	csvFile, err := os.Create(csvPath)
	if err != nil {
		jsonFile.Close()
		return nil, fmt.Errorf("failed to create CSV log file: %w", err)
	}
	ml.csvFile = csvFile
	ml.csvWriter = csv.NewWriter(csvFile)

	// Write CSV headers
	headers := []string{
		"timestamp", "market_id", "window_duration_sec",
		"position_count", "correct_positions", "wrong_positions", "win_rate_pct",
		"gross_profit_usdc", "total_fees_usdc", "net_profit_usdc", "avg_profit_pct",
		"avg_entry_price", "avg_exit_price", "total_size_traded",
		"final_up_price", "final_down_price", "resolution",
		"account_balance_usdc", "cumulative_profit_usdc",
	}
	ml.csvWriter.Write(headers)
	ml.csvWriter.Flush()

	return ml, nil
}

// LogMarketClosure logs a market window closure with all relevant metrics
func (ml *MarketLogger) LogMarketClosure(
	marketID string,
	closedPositions []*trading.ClosedPosition,
	finalPrices map[string]*polymarket.MarketBook,
	accountBalance float64,
	cumulativeProfit float64,
) error {
	ml.mu.Lock()
	defer ml.mu.Unlock()

	if ml.jsonFile == nil || ml.csvFile == nil {
		return fmt.Errorf("logger not initialized")
	}

	// Calculate metrics from closed positions
	log := ml.calculateMetrics(marketID, closedPositions, finalPrices, accountBalance, cumulativeProfit)

	// Write to JSON (JSONL format - one JSON object per line)
	jsonBytes, err := json.Marshal(log)
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}
	if _, err := ml.jsonFile.WriteString(string(jsonBytes) + "\n"); err != nil {
		return fmt.Errorf("failed to write JSON log: %w", err)
	}
	ml.jsonFile.Sync()

	// Write to CSV
	record := []string{
		log.Timestamp.Format(time.RFC3339),
		log.MarketID,
		fmt.Sprintf("%d", log.WindowDuration),
		fmt.Sprintf("%d", log.PositionCount),
		fmt.Sprintf("%d", log.CorrectPositions),
		fmt.Sprintf("%d", log.WrongPositions),
		fmt.Sprintf("%.2f", log.WinRate),
		fmt.Sprintf("%.4f", log.GrossProfit),
		fmt.Sprintf("%.4f", log.TotalFees),
		fmt.Sprintf("%.4f", log.NetProfit),
		fmt.Sprintf("%.2f", log.AverageProfitPct),
		fmt.Sprintf("%.4f", log.AvgEntryPrice),
		fmt.Sprintf("%.4f", log.AvgExitPrice),
		fmt.Sprintf("%.2f", log.TotalSizeTraded),
		fmt.Sprintf("%.4f", log.FinalUpPrice),
		fmt.Sprintf("%.4f", log.FinalDownPrice),
		log.Resolution,
		fmt.Sprintf("%.4f", log.AccountBalance),
		fmt.Sprintf("%.4f", log.CumulativeProfit),
	}
	ml.csvWriter.Write(record)
	ml.csvWriter.Flush()

	return nil
}

// calculateMetrics computes all performance metrics from closed positions
func (ml *MarketLogger) calculateMetrics(
	marketID string,
	closedPositions []*trading.ClosedPosition,
	finalPrices map[string]*polymarket.MarketBook,
	accountBalance float64,
	cumulativeProfit float64,
) *MarketPerformanceLog {
	log := &MarketPerformanceLog{
		MarketID:         marketID,
		Timestamp:        time.Now(),
		TimestampUnix:    time.Now().Unix(),
		WindowDuration:   300, // 5-minute window
		PositionCount:    len(closedPositions),
		AccountBalance:   accountBalance,
		CumulativeProfit: cumulativeProfit,
	}

	// Extract final prices
	upKey := marketID + "-UP"
	downKey := marketID + "-DOWN"

	if upBook, exists := finalPrices[upKey]; exists && upBook != nil {
		log.FinalUpPrice = upBook.BestBidParsed
	}
	if downBook, exists := finalPrices[downKey]; exists && downBook != nil {
		log.FinalDownPrice = downBook.BestBidParsed
	}

	// Determine resolution winner
	if log.FinalUpPrice > log.FinalDownPrice {
		log.Resolution = "UP"
	} else {
		log.Resolution = "DOWN"
	}

	// Calculate P&L and position metrics
	var totalGrossProfit float64
	var totalFees float64
	var totalEntryPrice float64
	var totalExitPrice float64
	var totalSize float64
	var sumProfitPct float64
	correctCount := 0

	for _, pos := range closedPositions {
		// Track if position was correct
		if pos.Outcome == log.Resolution {
			correctCount++
		}

		totalGrossProfit += pos.ProfitLoss
		totalFees += pos.EntryFee + pos.ExitFee
		totalEntryPrice += pos.EntryPrice * pos.Size
		totalExitPrice += pos.ExitPrice * pos.Size
		totalSize += pos.Size
		sumProfitPct += pos.ProfitPct
	}

	log.GrossProfit = totalGrossProfit
	log.TotalFees = totalFees
	log.NetProfit = totalGrossProfit - totalFees
	log.CorrectPositions = correctCount
	log.WrongPositions = log.PositionCount - correctCount

	if log.PositionCount > 0 {
		log.WinRate = (float64(correctCount) / float64(log.PositionCount)) * 100
		log.AverageProfitPct = sumProfitPct / float64(log.PositionCount)

		if totalSize > 0 {
			log.AvgEntryPrice = totalEntryPrice / totalSize
			log.AvgExitPrice = totalExitPrice / totalSize
		}
	}

	log.TotalSizeTraded = totalSize

	// Set window times
	now := time.Now().Unix()
	log.WindowEndTime = now
	log.WindowStartTime = now - 300 // 5 minutes ago

	return log
}

// Close closes all log files
func (ml *MarketLogger) Close() error {
	ml.mu.Lock()
	defer ml.mu.Unlock()

	var errs []error

	if ml.csvWriter != nil {
		ml.csvWriter.Flush()
	}

	if ml.csvFile != nil {
		if err := ml.csvFile.Close(); err != nil {
			errs = append(errs, fmt.Errorf("failed to close CSV file: %w", err))
		}
	}

	if ml.jsonFile != nil {
		if err := ml.jsonFile.Close(); err != nil {
			errs = append(errs, fmt.Errorf("failed to close JSON file: %w", err))
		}
	}

	if len(errs) > 0 {
		return fmt.Errorf("errors closing log files: %v", errs)
	}

	return nil
}

// GetSessionID returns the session ID for this logger
func (ml *MarketLogger) GetSessionID() string {
	return ml.sessionID
}

// GetLogDirectory returns the directory where logs are stored
func (ml *MarketLogger) GetLogDirectory() string {
	return ml.logDir
}
