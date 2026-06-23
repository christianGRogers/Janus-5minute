package strategies

import (
	"bytes"
	"encoding/json"
	"log"
	"math"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"janus-bot/pkg/analytics"
	"janus-bot/pkg/polymarket"
	"janus-bot/pkg/trading"
)

// swayPredictionSlots are the seconds-remaining values at which we run the model.
var swayPredictionSlots = []int{60, 30, 20, 15, 10}

// swayPredictionTolerance is how many seconds off the slot we still fire (±).
const swayPredictionTolerance = 3

// stopLossOffset is the per-share price drop that triggers an exit.
const stopLossOffset = 0.20

// SwayPrediction holds one model inference result.
type SwayPrediction struct {
	Outcome         string  // "UP" or "DOWN"
	Confidence      float64 // 0.0 – 1.0
	RawPrediction   float64 // raw model output (>0.5 → UP)
	FeaturesOK      bool
	RemainingAtPred int
	Timestamp       time.Time
}

// priceTick is one order-book mid-price observation.
type priceTick struct {
	UnixTime int64   // absolute unix timestamp
	Price    float64 // UP-outcome mid-price (0.0 – 1.0)
}

// SwayStrategy uses the v2 sway model to predict market direction and place orders.
//
// Every 5-second tick it:
//  1. Records the current UP-outcome mid-price for each live market.
//  2. At key remaining-time slots (60s, 30s, 20s, 15s, 10s), fires an async
//     Python inference call that writes a SwayPrediction for the market.
//  3. Checks open positions for two exit conditions (highest priority):
//     a. Stop-loss: best bid ≤ entry price − $0.20/share → sell all at best bid.
//     b. Outcome flip: fresh prediction now opposes the held outcome → sell all at best bid.
//  4. If no exit is needed, checks whether to open a new BUY position.
type SwayStrategy struct {
	*BaseStrategy

	// Rolling price history per market slug (UP outcome mid-prices only).
	historyMu    sync.Mutex
	priceHistory map[string][]priceTick

	// Latest prediction per market slug.
	predMu      sync.Mutex
	predictions map[string]*SwayPrediction

	// Which prediction slots have already fired for each market.
	predictedSlots map[string]map[int]bool

	// Inventory and exposure tracking.
	ownedInventory map[string]float64
	marketExposure map[string]float64

	// Position details needed for sell logic.
	positionOutcome    map[string]string  // marketID → "UP" or "DOWN"
	positionEntryPrice map[string]float64 // marketID → weighted-average entry price per share

	// pendingOutcome bridges EvaluateV2 (knows outcome) → OnOrderPlaced (doesn't).
	pendingOutcome map[string]string

	maxMarketExposure float64 // fraction of balance; default 0.35
	minConfidence     float64 // minimum model confidence required to trade

	// Python invocation.
	pythonBin       string
	modelScriptPath string
	retrainScript   string

	// Loss-triggered retrain (mirrors late_entry.go pattern).
	lossScriptPath string
	proxyAddress   string
	lastLossCount  int
	retraining     bool
	retrainingMu   sync.Mutex

	dashboard *analytics.Dashboard
}

// NewSwayStrategy creates and returns a configured SwayStrategy.
//
// Environment variables:
//
//	SWAY_PYTHON_BIN   – python executable (default: python3)
//	SWAY_SCRIPT_PATH  – path to sway_predict.py (default: sway_model/sway_predict.py)
func NewSwayStrategy(engine trading.TradingEngine) *SwayStrategy {
	pythonBin := os.Getenv("SWAY_PYTHON_BIN")
	if pythonBin == "" {
		pythonBin = "python3"
	}

	scriptPath := os.Getenv("SWAY_SCRIPT_PATH")
	if scriptPath == "" {
		scriptPath = "sway_model/sway_predict.py"
	}

	retrainScript := os.Getenv("SWAY_RETRAIN_SCRIPT")
	if retrainScript == "" {
		retrainScript = "sway_model/retrain.py"
	}

	lossScriptPath := os.Getenv("LOSS_SCRIPT_PATH")
	if lossScriptPath == "" {
		lossScriptPath = "tools/get_loss.py"
	}

	proxyAddress := os.Getenv("PROXY_ADDRESS")
	if proxyAddress == "" {
		log.Printf("[Sway] WARNING: PROXY_ADDRESS not set — loss-triggered retrain disabled")
	}

	log.Printf("[Sway] Initializing SwayStrategy | python=%s | script=%s | minConf=85%% | stopLoss=$%.2f/share",
		pythonBin, scriptPath, stopLossOffset)

	s := &SwayStrategy{
		BaseStrategy:       NewBaseStrategy(engine),
		priceHistory:       make(map[string][]priceTick),
		predictions:        make(map[string]*SwayPrediction),
		predictedSlots:     make(map[string]map[int]bool),
		ownedInventory:     make(map[string]float64),
		marketExposure:     make(map[string]float64),
		positionOutcome:    make(map[string]string),
		positionEntryPrice: make(map[string]float64),
		pendingOutcome:     make(map[string]string),
		maxMarketExposure:  0.35,
		minConfidence:      0.85,
		pythonBin:          pythonBin,
		modelScriptPath:    scriptPath,
		retrainScript:      retrainScript,
		lossScriptPath:     lossScriptPath,
		proxyAddress:       proxyAddress,
		lastLossCount:      -1, // -1 so first window-change always syncs the count
	}
	s.Config.RiskTolerance = 0.20

	// Retrain immediately on startup so the model reflects the latest market regime.
	s.triggerRetrain()

	return s
}

func (ss *SwayStrategy) Name() string { return "Sway" }

func (ss *SwayStrategy) SetDashboard(d *analytics.Dashboard) { ss.dashboard = d }

// EvaluateV2 is called every 5 seconds by main.go.
func (ss *SwayStrategy) EvaluateV2(markets map[string]*polymarket.MarketBook) *TradeSignal {
	now := time.Now()
	windowStart := (now.Unix() / 300) * 300
	secondsRemaining := 300 - int(now.Unix()-windowStart)

	// ── Phase 1: collect price history + fire predictions (always) ───────────
	for cacheKey, book := range markets {
		if book == nil {
			continue
		}

		if !strings.HasSuffix(cacheKey, "-UP") {
			continue
		}

		marketID := cacheKey[:len(cacheKey)-3]
		marketStart, ok := swayParseMarketStart(marketID)
		if !ok {
			continue
		}

		elapsed := now.Unix() - marketStart
		if elapsed < 0 || elapsed > 310 {
			continue
		}

		midPrice := (book.BestBidParsed + book.BestAskParsed) / 2
		if midPrice <= 0 {
			continue
		}

		ss.historyMu.Lock()
		ss.priceHistory[marketID] = append(ss.priceHistory[marketID], priceTick{
			UnixTime: now.Unix(),
			Price:    midPrice,
		})
		ss.historyMu.Unlock()

		for _, slot := range swayPredictionSlots {
			if swayAbsInt(secondsRemaining-slot) <= swayPredictionTolerance {
				ss.predMu.Lock()
				if ss.predictedSlots[marketID] == nil {
					ss.predictedSlots[marketID] = make(map[int]bool)
				}
				alreadyFired := ss.predictedSlots[marketID][slot]
				if !alreadyFired {
					ss.predictedSlots[marketID][slot] = true
				}
				ss.predMu.Unlock()

				if !alreadyFired {
					go ss.runPrediction(marketID, marketStart, int(elapsed), slot)
				}
			}
		}
	}

	// ── Phase 2: sell checks — run regardless of time remaining ──────────────
	//
	// We always want to be able to exit a bad position even outside the 65s window,
	// so sell checks run before the time gate.
	if sig := ss.checkExits(markets, now); sig != nil {
		return sig
	}

	// ── Phase 3: buy — only in final 65 s ────────────────────────────────────
	if secondsRemaining > 65 {
		return &TradeSignal{ShouldTrade: false}
	}

	return ss.checkEntry(markets, now)
}

// checkExits scans open positions for stop-loss and outcome-flip conditions.
// Stop-loss takes priority over outcome flip.
func (ss *SwayStrategy) checkExits(markets map[string]*polymarket.MarketBook, now time.Time) *TradeSignal {
	for marketID, shares := range ss.ownedInventory {
		if shares < 0.5 {
			continue
		}

		heldOutcome := ss.positionOutcome[marketID]
		if heldOutcome == "" {
			continue
		}

		entryPrice := ss.positionEntryPrice[marketID]
		stopPrice := entryPrice - stopLossOffset

		// Get the live book for the outcome we're holding.
		book := markets[marketID+"-"+heldOutcome]
		if book == nil || book.BestBidParsed == 0 {
			continue
		}

		stopTriggered := book.BestBidParsed <= stopPrice

		// Outcome flip: fresh prediction (≤35s old, conf ≥ threshold) disagrees.
		flipTriggered := false
		ss.predMu.Lock()
		pred := ss.predictions[marketID]
		ss.predMu.Unlock()
		if pred != nil && pred.FeaturesOK &&
			pred.Outcome != heldOutcome &&
			pred.Confidence >= ss.minConfidence &&
			now.Sub(pred.Timestamp) <= 35*time.Second {
			flipTriggered = true
		}

		if !stopTriggered && !flipTriggered {
			continue
		}

		reason := "outcome_flip"
		if stopTriggered {
			reason = "stop_loss"
		}

		// Sell as many shares as the best bid can absorb this tick.
		sellShares := math.Min(shares, book.BestBidSizeParsed*0.90)
		if sellShares < 0.5 {
			sellShares = shares // try anyway if liquidity is very low
		}

		log.Printf("[Sway] SELL | reason=%s | market=%s | held=%s | shares=%.1f | bid=%.4f | entry=%.4f | stopAt=%.4f",
			reason, marketID, heldOutcome, sellShares, book.BestBidParsed, entryPrice, stopPrice)

		return &TradeSignal{
			ShouldTrade:        true,
			MarketID:           marketID,
			Side:               "SELL",
			Price:              book.BestBidParsed,
			Size:               sellShares,
			AvailableLiquidity: book.BestBidSizeParsed,
			Outcome:            heldOutcome,
		}
	}
	return nil
}

// checkEntry looks for a BUY opportunity based on the latest model prediction.
func (ss *SwayStrategy) checkEntry(markets map[string]*polymarket.MarketBook, now time.Time) *TradeSignal {
	for cacheKey, book := range markets {
		if book == nil || book.BestAskParsed == 0 {
			continue
		}

		// If nobody is selling this outcome (empty ask side), the UP mid-price
		// signal becomes stale and can produce misleading sway — skip entirely.
		if book.BestAskSizeParsed < 1.0 {
			continue
		}

		var outcome, marketID string
		switch {
		case strings.HasSuffix(cacheKey, "-UP"):
			outcome = "UP"
			marketID = cacheKey[:len(cacheKey)-3]
		case strings.HasSuffix(cacheKey, "-DOWN"):
			outcome = "DOWN"
			marketID = cacheKey[:len(cacheKey)-5]
		default:
			continue
		}

		ss.predMu.Lock()
		pred := ss.predictions[marketID]
		ss.predMu.Unlock()

		if pred == nil || !pred.FeaturesOK {
			continue
		}
		if now.Sub(pred.Timestamp) > 35*time.Second {
			continue
		}
		// Only trade on predictions made at ≤30s remaining — the 60s prediction
		// has the least market data and is the least reliable.
		if pred.RemainingAtPred > 30 {
			continue
		}
		if pred.Outcome != outcome || pred.Confidence < ss.minConfidence {
			continue
		}

		// Never open a position if the market is pricing this outcome below $0.85.
		if book.BestAskParsed < 0.85 {
			continue
		}

		// Don't add to a position that's already on the opposite outcome.
		if existing := ss.positionOutcome[marketID]; existing != "" && existing != outcome {
			continue
		}

		balance := ss.Engine.GetBalance()
		currentExposure := ss.marketExposure[marketID]
		maxExposure := balance * ss.maxMarketExposure
		if currentExposure >= maxExposure {
			continue
		}

		// Scale position by confidence above threshold: 0.5× at min conf → 1.0× at 100%.
		baseUSDC := ss.GetDynamicPositionSize()
		confScale := math.Min(1.0, (pred.Confidence-ss.minConfidence)/(1.0-ss.minConfidence)+0.5)
		positionUSDC := math.Min(baseUSDC*confScale, maxExposure-currentExposure)
		positionShares := positionUSDC / book.BestAskParsed

		if positionShares < 0.5 {
			continue
		}
		positionShares = math.Min(positionShares, book.BestAskSizeParsed*0.75)
		if positionShares < 0.5 {
			continue
		}

		log.Printf("[Sway] BUY | market=%s | outcome=%s | conf=%.1f%% | raw=%.4f | price=%.4f | shares=%.1f | stopLoss=%.4f | predAt=%ds",
			marketID, outcome, pred.Confidence*100, pred.RawPrediction,
			book.BestAskParsed, positionShares, book.BestAskParsed-stopLossOffset, pred.RemainingAtPred)

		ss.pendingOutcome[marketID] = outcome

		return &TradeSignal{
			ShouldTrade:        true,
			MarketID:           marketID,
			Side:               "BUY",
			Price:              book.BestAskParsed,
			Size:               positionShares,
			AvailableLiquidity: book.BestAskSizeParsed,
			Outcome:            outcome,
		}
	}
	return &TradeSignal{ShouldTrade: false}
}

// runPrediction copies the current price history, calls the Python model, and
// stores the result. Runs in a goroutine — never blocks EvaluateV2.
func (ss *SwayStrategy) runPrediction(marketID string, marketStart int64, elapsed int, remaining int) {
	ss.historyMu.Lock()
	src := ss.priceHistory[marketID]
	history := make([]priceTick, len(src))
	copy(history, src)
	ss.historyMu.Unlock()

	if len(history) < 3 {
		log.Printf("[Sway] Skipping prediction for %s at %ds remaining: only %d price ticks",
			marketID, remaining, len(history))
		return
	}

	times := make([]float64, len(history))
	prices := make([]float64, len(history))
	for i, t := range history {
		times[i] = float64(t.UnixTime)
		prices[i] = t.Price
	}

	payload := map[string]interface{}{
		"times":        times,
		"prices":       prices,
		"market_start": float64(marketStart),
		"elapsed":      elapsed,
		"remaining":    remaining,
	}
	inputJSON, err := json.Marshal(payload)
	if err != nil {
		log.Printf("[Sway] Failed to marshal prediction input for %s: %v", marketID, err)
		return
	}

	cmd := exec.Command(ss.pythonBin, ss.modelScriptPath)
	cmd.Stdin = bytes.NewReader(inputJSON)

	out, err := cmd.Output()
	if err != nil {
		log.Printf("[Sway] Python inference failed for %s at %ds remaining: %v", marketID, remaining, err)
		return
	}

	var result struct {
		Outcome       string             `json:"outcome"`
		Confidence    float64            `json:"confidence"`
		RawPrediction float64            `json:"raw_prediction"`
		FeaturesOK    bool               `json:"features_computed"`
		Error         string             `json:"error"`
		SwayValues    map[string]float64 `json:"sway_values"`
		SwayAgreement float64            `json:"sway_agreement"`
		SwayMagnitude float64            `json:"sway_magnitude"`
		ShortLongDiv  float64            `json:"short_long_div"`
		TimeRemaining int                `json:"time_remaining"`
	}
	if err := json.Unmarshal(out, &result); err != nil {
		log.Printf("[Sway] Bad JSON from inference script for %s: %v | output: %s", marketID, err, string(out))
		return
	}

	if result.Error != "" {
		log.Printf("[Sway] Inference error for %s at %ds remaining: %s", marketID, remaining, result.Error)
	}

	swayByWindow := make(map[int]float64)
	windowKeys := map[string]int{"sway_10s": 10, "sway_15s": 15, "sway_20s": 20, "sway_30s": 30, "sway_60s": 60}
	for k, v := range result.SwayValues {
		if w, ok := windowKeys[k]; ok {
			swayByWindow[w] = v
		}
	}

	now := time.Now()

	pred := &SwayPrediction{
		Outcome:         result.Outcome,
		Confidence:      result.Confidence,
		RawPrediction:   result.RawPrediction,
		FeaturesOK:      result.FeaturesOK,
		RemainingAtPred: remaining,
		Timestamp:       now,
	}

	ss.predMu.Lock()
	ss.predictions[marketID] = pred
	ss.predMu.Unlock()

	log.Printf("[Sway] PREDICTION | market=%s | %ds remaining | outcome=%s | confidence=%.1f%% | raw=%.4f | features=%v",
		marketID, remaining, pred.Outcome, pred.Confidence*100, pred.RawPrediction, pred.FeaturesOK)

	if ss.dashboard != nil {
		ss.dashboard.SetSwayState(&analytics.SwayModelState{
			MarketID:        marketID,
			Outcome:         result.Outcome,
			Confidence:      result.Confidence,
			RawPrediction:   result.RawPrediction,
			FeaturesOK:      result.FeaturesOK,
			RemainingAtPred: remaining,
			PredictedAt:     now,
			SwayValues:      swayByWindow,
			SwayAgreement:   result.SwayAgreement,
			SwayMagnitude:   result.SwayMagnitude,
			ShortLongDiv:    result.ShortLongDiv,
		})
	}
}

// OnOrderPlaced updates inventory and position tracking after an order executes.
func (ss *SwayStrategy) OnOrderPlaced(marketID string, side string, price float64, size float64) {
	cost := price * size
	if side == "BUY" {
		// Weighted-average entry price across multiple fills.
		prevShares := ss.ownedInventory[marketID]
		newShares := prevShares + size
		if newShares > 0 {
			ss.positionEntryPrice[marketID] = (ss.positionEntryPrice[marketID]*prevShares + price*size) / newShares
		}
		ss.ownedInventory[marketID] = newShares
		ss.marketExposure[marketID] += cost

		// Capture which outcome this buy was for.
		if outcome, ok := ss.pendingOutcome[marketID]; ok {
			ss.positionOutcome[marketID] = outcome
			delete(ss.pendingOutcome, marketID)
		}

		stopAt := ss.positionEntryPrice[marketID] - stopLossOffset
		log.Printf("[Sway] Order recorded | market=%s | BUY %.1f @ %.4f | avgEntry=%.4f | stopLoss=%.4f | exposure=$%.2f",
			marketID, size, price, ss.positionEntryPrice[marketID], stopAt, ss.marketExposure[marketID])

	} else if side == "SELL" {
		ss.ownedInventory[marketID] -= size
		if ss.ownedInventory[marketID] < 0.5 {
			ss.ownedInventory[marketID] = 0
			// Clear position metadata when fully exited.
			delete(ss.positionOutcome, marketID)
			delete(ss.positionEntryPrice, marketID)
		}
		ss.marketExposure[marketID] -= cost
		if ss.marketExposure[marketID] < 0 {
			ss.marketExposure[marketID] = 0
		}
		log.Printf("[Sway] Order recorded | market=%s | SELL %.1f @ %.4f | remaining=%.1f shares | exposure=$%.2f",
			marketID, size, price, ss.ownedInventory[marketID], ss.marketExposure[marketID])
	}
}

// OnMarketWindowChange resets all per-window state when the 5-min window rolls over.
func (ss *SwayStrategy) OnMarketWindowChange() {
	ss.historyMu.Lock()
	ss.priceHistory = make(map[string][]priceTick)
	ss.historyMu.Unlock()

	ss.predMu.Lock()
	ss.predictions = make(map[string]*SwayPrediction)
	ss.predictedSlots = make(map[string]map[int]bool)
	ss.predMu.Unlock()

	ss.ownedInventory = make(map[string]float64)
	ss.marketExposure = make(map[string]float64)
	ss.positionOutcome = make(map[string]string)
	ss.positionEntryPrice = make(map[string]float64)
	ss.pendingOutcome = make(map[string]string)

	log.Printf("[Sway] Market window rolled over — all state reset")

	// Check for new losses and retrain if the count increased.
	go ss.checkAndRetrain()
}

// Reset clears all internal state (alias for OnMarketWindowChange).
func (ss *SwayStrategy) Reset() {
	ss.OnMarketWindowChange()
}

// ── Retraining ───────────────────────────────────────────────────────────────

// triggerRetrain launches retrain.py in a background goroutine.
// It is a no-op if a retrain is already running.
func (ss *SwayStrategy) triggerRetrain() {
	ss.retrainingMu.Lock()
	if ss.retraining {
		ss.retrainingMu.Unlock()
		log.Printf("[Sway] Retrain already in progress — skipping")
		return
	}
	ss.retraining = true
	ss.retrainingMu.Unlock()

	go func() {
		defer func() {
			ss.retrainingMu.Lock()
			ss.retraining = false
			ss.retrainingMu.Unlock()
		}()

		log.Printf("[Sway] Retrain started (latest 600 markets → sway_model_live.pkl)")
		cmd := exec.Command(ss.pythonBin, ss.retrainScript)
		cmd.Stdout = os.Stdout
		cmd.Stderr = os.Stderr
		if err := cmd.Run(); err != nil {
			log.Printf("[Sway] Retrain failed: %v", err)
		} else {
			log.Printf("[Sway] Retrain complete — model updated")
		}
	}()
}

// checkAndRetrain calls get_loss.py and triggers a retrain if the loss count
// has increased since the last window change.
func (ss *SwayStrategy) checkAndRetrain() {
	if ss.proxyAddress == "" {
		return
	}

	cmd := exec.Command(ss.pythonBin, ss.lossScriptPath)
	cmd.Env = append(os.Environ(), "PROXY_ADDRESS="+ss.proxyAddress)
	out, err := cmd.Output()
	if err != nil {
		log.Printf("[Sway] get_loss.py failed: %v", err)
		return
	}

	countStr := strings.TrimSpace(string(out))
	count, err := strconv.Atoi(countStr)
	if err != nil {
		log.Printf("[Sway] get_loss.py returned non-integer: %q", countStr)
		return
	}

	if ss.lastLossCount < 0 {
		// First call — just record the baseline, don't retrain.
		ss.lastLossCount = count
		log.Printf("[Sway] Loss baseline: %d losses in last 3h", count)
		return
	}

	if count > ss.lastLossCount {
		log.Printf("[Sway] New loss detected (%d → %d losses) — triggering retrain", ss.lastLossCount, count)
		ss.lastLossCount = count
		ss.triggerRetrain()
	} else {
		ss.lastLossCount = count
	}
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func swayParseMarketStart(slug string) (int64, bool) {
	parts := strings.Split(slug, "-")
	if len(parts) == 0 {
		return 0, false
	}
	ts, err := strconv.ParseInt(parts[len(parts)-1], 10, 64)
	if err != nil {
		return 0, false
	}
	return ts, true
}

func swayAbsInt(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
