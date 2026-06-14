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
//  3. Once a prediction exists with confidence ≥ minConfidence, returns a BUY
//     signal on the predicted outcome.
//
// Model output (outcome + confidence) is logged on every prediction and on every
// trade signal so it is always visible in the bot logs.
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
	ownedInventory    map[string]float64
	marketExposure    map[string]float64
	maxMarketExposure float64 // fraction of balance; default 0.35

	// Minimum model confidence required to trade.
	minConfidence float64

	// Python invocation.
	pythonBin       string
	modelScriptPath string

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

	log.Printf("[Sway] Initializing SwayStrategy | python=%s | script=%s | minConf=55%%", pythonBin, scriptPath)

	s := &SwayStrategy{
		BaseStrategy:      NewBaseStrategy(engine),
		priceHistory:      make(map[string][]priceTick),
		predictions:       make(map[string]*SwayPrediction),
		predictedSlots:    make(map[string]map[int]bool),
		ownedInventory:    make(map[string]float64),
		marketExposure:    make(map[string]float64),
		maxMarketExposure: 0.35,
		minConfidence:     0.55,
		pythonBin:         pythonBin,
		modelScriptPath:   scriptPath,
	}
	s.Config.RiskTolerance = 0.20
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

		// Only the UP outcome carries the directional price signal.
		if !strings.HasSuffix(cacheKey, "-UP") {
			continue
		}

		marketID := cacheKey[:len(cacheKey)-3] // strip "-UP"
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

		// Record tick.
		ss.historyMu.Lock()
		ss.priceHistory[marketID] = append(ss.priceHistory[marketID], priceTick{
			UnixTime: now.Unix(),
			Price:    midPrice,
		})
		ss.historyMu.Unlock()

		// Fire prediction at each key remaining-time slot (once per slot).
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

	// ── Phase 2: trading decision (only in final 65 s) ───────────────────────
	if secondsRemaining > 65 {
		return &TradeSignal{ShouldTrade: false}
	}

	for cacheKey, book := range markets {
		if book == nil || book.BestAskParsed == 0 {
			continue
		}

		var outcome string
		var marketID string

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

		if book.LiquidityParsed < ss.Config.MinLiquidityUSDC {
			continue
		}

		ss.predMu.Lock()
		pred := ss.predictions[marketID]
		ss.predMu.Unlock()

		if pred == nil || !pred.FeaturesOK {
			continue
		}

		// Discard stale predictions (older than 35 s).
		if now.Sub(pred.Timestamp) > 35*time.Second {
			continue
		}

		// Trade only when the model agrees with this outcome and confidence is sufficient.
		if pred.Outcome != outcome || pred.Confidence < ss.minConfidence {
			continue
		}

		// Per-market exposure cap.
		balance := ss.Engine.GetBalance()
		currentExposure := ss.marketExposure[marketID]
		maxExposure := balance * ss.maxMarketExposure
		if currentExposure >= maxExposure {
			continue
		}

		// Scale position size by confidence above threshold.
		baseUSDC := ss.GetDynamicPositionSize()
		confScale := math.Min(1.0, (pred.Confidence-ss.minConfidence)/(1.0-ss.minConfidence)+0.5)
		positionUSDC := math.Min(baseUSDC*confScale, maxExposure-currentExposure)
		positionShares := positionUSDC / book.BestAskParsed

		if positionShares < 0.5 {
			continue
		}

		// Don't consume more than 75 % of the available liquidity at the ask.
		positionShares = math.Min(positionShares, book.BestAskSizeParsed*0.75)
		if positionShares < 0.5 {
			continue
		}

		log.Printf("[Sway] TRADE SIGNAL | market=%s | predicted=%s | confidence=%.1f%% | raw=%.4f | side=BUY %s | price=%.4f | shares=%.1f | predAt=%ds remaining",
			marketID, pred.Outcome, pred.Confidence*100, pred.RawPrediction,
			outcome, book.BestAskParsed, positionShares, pred.RemainingAtPred)

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
// stores the result.  Runs in a goroutine — never blocks EvaluateV2.
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

	// Build JSON payload for sway_predict.py.
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
		SwayValues    map[string]float64 `json:"sway_values"`     // "sway_10s" → float
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

	// Convert string-keyed sway map → int-keyed
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

	// Push to dashboard so the sway section always reflects the latest inference.
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

// OnOrderPlaced updates the inventory and exposure state after an order executes.
func (ss *SwayStrategy) OnOrderPlaced(marketID string, side string, price float64, size float64) {
	cost := price * size
	if side == "BUY" {
		ss.ownedInventory[marketID] += size
		ss.marketExposure[marketID] += cost
	} else if side == "SELL" {
		ss.ownedInventory[marketID] -= size
		if ss.ownedInventory[marketID] < 0 {
			ss.ownedInventory[marketID] = 0
		}
		ss.marketExposure[marketID] -= cost
		if ss.marketExposure[marketID] < 0 {
			ss.marketExposure[marketID] = 0
		}
	}
	log.Printf("[Sway] Order recorded | market=%s | %s %.1f @ %.4f | exposure=$%.2f",
		marketID, side, size, price, ss.marketExposure[marketID])
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

	log.Printf("[Sway] Market window rolled over — all state reset")
}

// Reset clears all internal state (alias for OnMarketWindowChange).
func (ss *SwayStrategy) Reset() {
	ss.OnMarketWindowChange()
}

// ── Helpers ──────────────────────────────────────────────────────────────────

// swayParseMarketStart extracts the Unix timestamp embedded in a market slug
// like "btc-updown-5m-1779480300".
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
