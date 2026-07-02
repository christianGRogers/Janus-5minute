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

// Continuous prediction window: the model is re-run every second while the
// seconds-remaining is in [swayPredictFloor, swayPredictCeil]. This replaces
// the old discrete slot grid ({60,30,20,15,10}±3) so the bot can enter at any
// second the confidence/edge/price line up, not just at coarse checkpoints.
// The bounds match the range the model is trained on (see REMAINING_TIMES in
// strategies/models.py) so inference never extrapolates past trained times.
const swayPredictCeil = 60  // start predicting at 60s remaining
const swayPredictFloor = 10 // stop predicting at 10s remaining

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
// Every tick it:
//  1. Records the current UP-outcome mid-price for each live market.
//  2. While the market sits in the prediction window (60s→10s remaining),
//     fires an async Python inference every second (one at a time per market)
//     that writes a SwayPrediction, so entries can happen at any second.
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

	// Continuous prediction bookkeeping (per market):
	//   predInFlight   — a python inference is currently running, so we don't
	//                    stack overlapping processes; the next fire waits for it.
	//   lastPredSecond — the seconds-remaining value we last fired at, so we
	//                    fire at most once per integer second.
	predInFlight   map[string]bool
	lastPredSecond map[string]int

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
	maxEntryPrice     float64 // skip buys priced above this (avoid negative-skew near-resolution bets)
	minEntryPrice     float64 // skip buys priced below this (avoid contrarian "wrong side" longshots)
	minEdge           float64 // required model-vs-market divergence (positive-EV margin)
	maxRemaining      int     // only trade at/under this many seconds remaining

	// Python invocation.
	pythonBin       string
	modelScriptPath string
	retrainScript   string
	asset           string // asset prefix sent to the predictor (e.g. "btc")

	// Loss-triggered retrain (mirrors late_entry.go pattern).
	lossScriptPath string
	proxyAddress   string
	lastLossCount  int
	retraining     bool
	retrainingMu   sync.Mutex

	// Session-wide prediction stats for dashboard display.
	sessionPredCount int
	sessionConfSum   float64
	sessionMu        sync.Mutex

	dashboard *analytics.Dashboard
}

// NewSwayStrategy creates and returns a configured SwayStrategy.
//
// Environment variables:
//
//	SWAY_PYTHON_BIN     – python executable (default: python3)
//	SWAY_USE_LEGACY     – "1"/"true" to fall back to the original sway model
//	                      (sway_model/sway_predict.py + retrain.py). By default
//	                      the live strategy uses the spot+market fusion model
//	                      (strategies/spot_predict.py + retrain_combined.py).
//	SWAY_SCRIPT_PATH    – override predictor path (wins over SWAY_USE_LEGACY)
//	SWAY_RETRAIN_SCRIPT – override retrain script path
//	SWAY_ASSET          – asset prefix for the predictor, e.g. "btc" (default: btc)
//	SWAY_MIN_CONF       – min model confidence to trade (default 0.20)
//	SWAY_MAX_PRICE      – max entry (ask) price; skip pricier bets (default 0.80)
//	SWAY_MIN_PRICE      – min entry (ask) price; skip cheaper contrarian bets (default 0.50)
//	SWAY_MIN_EDGE       – required model-vs-market divergence for +EV (default 0.05)
//	SWAY_MAX_REMAINING  – only trade at/under this seconds-remaining (default 60)
// envFloat returns the float value of env var `key`, or `def` if unset/invalid.
func envFloat(key string, def float64) float64 {
	if v := os.Getenv(key); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return def
}

// envInt returns the int value of env var `key`, or `def` if unset/invalid.
func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func NewSwayStrategy(engine trading.TradingEngine) *SwayStrategy {
	pythonBin := os.Getenv("SWAY_PYTHON_BIN")
	if pythonBin == "" {
		pythonBin = "python3"
	}

	// The spot+market fusion model (the strategy-research winner) is the live
	// default. Set SWAY_USE_LEGACY=1 to fall back to the original sway model.
	// Explicit SWAY_SCRIPT_PATH/SWAY_RETRAIN_SCRIPT overrides still win.
	useLegacy := os.Getenv("SWAY_USE_LEGACY") == "1" ||
		strings.EqualFold(os.Getenv("SWAY_USE_LEGACY"), "true")

	defaultScript := "strategies/spot_predict.py"
	defaultRetrain := "strategies/retrain_combined.py"
	if useLegacy {
		defaultScript = "sway_model/sway_predict.py"
		defaultRetrain = "sway_model/retrain.py"
		log.Printf("[Sway] SWAY_USE_LEGACY enabled — using legacy sway model")
	} else {
		log.Printf("[Sway] Using spot+market fusion model (Combined-GBM)")
	}

	scriptPath := os.Getenv("SWAY_SCRIPT_PATH")
	if scriptPath == "" {
		scriptPath = defaultScript
	}

	retrainScript := os.Getenv("SWAY_RETRAIN_SCRIPT")
	if retrainScript == "" {
		retrainScript = defaultRetrain
	}

	asset := os.Getenv("SWAY_ASSET")
	if asset == "" {
		asset = "btc"
	}

	lossScriptPath := os.Getenv("LOSS_SCRIPT_PATH")
	if lossScriptPath == "" {
		lossScriptPath = "tools/get_loss.py"
	}

	proxyAddress := os.Getenv("PROXY_ADDRESS")
	if proxyAddress == "" {
		log.Printf("[Sway] WARNING: PROXY_ADDRESS not set — loss-triggered retrain disabled")
	}

	// Entry gates (tuned on out-of-sample backtests). The old defaults only
	// bought outcomes already priced >=0.85 with no edge check, which forces
	// negative-skew "pennies at 0.9+" bets. New defaults require a positive-EV
	// divergence from the market and cap the entry price.
	// NB: minConf must stay low enough that it doesn't collide with maxEntryPrice
	// — a high confidence gate forces raw>=0.8, but then the market ask is usually
	// also high and gets rejected by the price cap, so almost nothing trades. The
	// real signal is the edge (model vs ask); confidence is just a coin-flip filter.
	minConf := envFloat("SWAY_MIN_CONF", 0.20)
	maxEntryPrice := envFloat("SWAY_MAX_PRICE", 0.80)
	// Floor on the entry ask: buying an outcome the market prices below ~0.50
	// means betting against the crowd's directional call. On fast 5-min BTC
	// markets the resting ask is usually better-informed than the model, so a
	// large modelProb-vs-ask "edge" at a low price is adverse selection, not
	// free money (e.g. buying at 0.34 then losing). Only take the market's
	// favored side, where the model additionally sees edge.
	minEntryPrice := envFloat("SWAY_MIN_PRICE", 0.50)
	minEdge := envFloat("SWAY_MIN_EDGE", 0.05)
	maxRemaining := envInt("SWAY_MAX_REMAINING", 60)

	log.Printf("[Sway] Initializing SwayStrategy | python=%s | script=%s | minConf=%.2f | minPrice=%.2f | maxPrice=%.2f | minEdge=%.2f | maxRem=%ds | stopLoss=$%.2f/share",
		pythonBin, scriptPath, minConf, minEntryPrice, maxEntryPrice, minEdge, maxRemaining, stopLossOffset)

	s := &SwayStrategy{
		BaseStrategy:       NewBaseStrategy(engine),
		priceHistory:       make(map[string][]priceTick),
		predictions:        make(map[string]*SwayPrediction),
		predInFlight:       make(map[string]bool),
		lastPredSecond:     make(map[string]int),
		ownedInventory:     make(map[string]float64),
		marketExposure:     make(map[string]float64),
		positionOutcome:    make(map[string]string),
		positionEntryPrice: make(map[string]float64),
		pendingOutcome:     make(map[string]string),
		maxMarketExposure:  0.35,
		minConfidence:      minConf,
		maxEntryPrice:      maxEntryPrice,
		minEntryPrice:      minEntryPrice,
		minEdge:            minEdge,
		maxRemaining:       maxRemaining,
		pythonBin:          pythonBin,
		modelScriptPath:    scriptPath,
		retrainScript:      retrainScript,
		asset:              asset,
		lossScriptPath:     lossScriptPath,
		proxyAddress:       proxyAddress,
		lastLossCount:      -1,
	}
	s.Config.RiskTolerance = 0.20

	// Retrain immediately on startup so the model reflects the latest market regime.
	s.triggerRetrain()

	// Periodic retrain every 5 hours regardless of loss activity.
	go func() {
		ticker := time.NewTicker(5 * time.Hour)
		defer ticker.Stop()
		for range ticker.C {
			log.Printf("[Sway] Periodic 5-hour retrain triggered")
			s.triggerRetrain()
		}
	}()

	return s
}

func (ss *SwayStrategy) Name() string { return "Sway" }

func (ss *SwayStrategy) SetDashboard(d *analytics.Dashboard) {
	ss.dashboard = d
	if d != nil {
		// Show the active model immediately (before the first prediction fills
		// in the full identity), so the dashboard never sits on "(loading...)".
		name := "combined"
		if strings.Contains(ss.modelScriptPath, "sway_predict") {
			name = "sway"
		}
		d.SetModelInfo(&analytics.ModelInfo{Name: name})
	}
}

// EvaluateV2 is called every second by main.go.
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

		// Continuous cadence: fire an inference every second the market sits in
		// the prediction window, as long as one isn't already running for it.
		if secondsRemaining >= swayPredictFloor && secondsRemaining <= swayPredictCeil {
			ss.predMu.Lock()
			// Fire at most once per integer second, and never while a previous
			// inference for this market is still in flight (avoids stacking
			// python processes / Binance fetches).
			fire := !ss.predInFlight[marketID] && ss.lastPredSecond[marketID] != secondsRemaining
			if fire {
				ss.predInFlight[marketID] = true
				ss.lastPredSecond[marketID] = secondsRemaining
			}
			ss.predMu.Unlock()

			if fire {
				ss.retrainingMu.Lock()
				isRetraining := ss.retraining
				ss.retrainingMu.Unlock()

				if isRetraining {
					// Release the in-flight/second guard so the next tick retries
					// once the retrain finishes.
					ss.predMu.Lock()
					ss.predInFlight[marketID] = false
					ss.lastPredSecond[marketID] = 0
					ss.predMu.Unlock()
					log.Printf("[Sway] Skipping %ds prediction for %s — retrain in progress", secondsRemaining, marketID)
				} else {
					go func(mID string, mStart int64, el, rem int) {
						ss.runPrediction(mID, mStart, el, rem)
						ss.predMu.Lock()
						ss.predInFlight[mID] = false
						ss.predMu.Unlock()
					}(marketID, marketStart, int(elapsed), secondsRemaining)
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
	ss.retrainingMu.Lock()
	isRetraining := ss.retraining
	ss.retrainingMu.Unlock()
	if isRetraining {
		log.Printf("[Sway] Retraining in progress — BUY paused")
		return &TradeSignal{ShouldTrade: false}
	}

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
		if pred.RemainingAtPred > ss.maxRemaining {
			continue
		}
		if pred.Outcome != outcome || pred.Confidence < ss.minConfidence {
			continue
		}

		// Positive-EV divergence: the model's probability for THIS outcome must
		// exceed the market ask by at least minEdge. (RawPrediction is P(UP).)
		// This is the edge — buying where the crowd underprices the outcome —
		// rather than the old logic that just bought near-certain outcomes.
		modelProb := pred.RawPrediction
		if outcome == "DOWN" {
			modelProb = 1.0 - pred.RawPrediction
		}
		if modelProb-book.BestAskParsed < ss.minEdge {
			continue
		}

		// Avoid negative-skew near-resolution bets: at prices near 1.0 the win
		// margin is a few cents while a loss costs the whole stake, so one loss
		// wipes ~12 wins. Skip anything priced above maxEntryPrice.
		if book.BestAskParsed > ss.maxEntryPrice {
			continue
		}

		// Avoid contrarian "wrong side" longshots: an outcome the market prices
		// below minEntryPrice is one the crowd thinks is unlikely. On fast 5-min
		// markets a large model-vs-ask edge at a low ask is usually the model
		// being wrong (adverse selection), so skip it and only trade the
		// market's favored side.
		if book.BestAskParsed < ss.minEntryPrice {
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
		"asset":        ss.asset, // ignored by sway_predict.py; used by spot_predict.py
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
		// Combined (spot+market) model signals
		SpotLeadBps     float64 `json:"spot_lead_bps"`
		SpotBarrierProb float64 `json:"spot_barrier_prob"`
		MarketPrice     float64 `json:"market_price"`
		SpotPrice       float64 `json:"spot_price"`
		SpotOpen        float64 `json:"spot_open"`
		// Model identity fields populated by sway_predict.py
		ModelVersion      string  `json:"model_version"`
		ModelAccuracy     float64 `json:"model_accuracy"`
		ModelR2           float64 `json:"model_r2"`
		ModelMarkets      int     `json:"model_markets"`
		ModelTrainingDate string  `json:"model_training_date"`
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

	log.Printf("[Sway] PREDICTION | market=%s | %ds remaining | outcome=%s | confidence=%.1f%% | raw=%.4f | features=%v | model=%s",
		marketID, remaining, pred.Outcome, pred.Confidence*100, pred.RawPrediction, pred.FeaturesOK, result.ModelVersion)

	// Update session-level confidence rolling average.
	ss.sessionMu.Lock()
	if result.FeaturesOK {
		ss.sessionPredCount++
		ss.sessionConfSum += result.Confidence
	}
	avgConf := 0.0
	if ss.sessionPredCount > 0 {
		avgConf = ss.sessionConfSum / float64(ss.sessionPredCount)
	}
	predCount := ss.sessionPredCount
	ss.sessionMu.Unlock()

	if ss.dashboard != nil {
		ss.dashboard.SetModelInfo(&analytics.ModelInfo{
			Name:      result.ModelVersion,
			Accuracy:  result.ModelAccuracy,
			AvgR2:     result.ModelR2,
			Markets:   result.ModelMarkets,
			TrainedAt: result.ModelTrainingDate,
			AvgConf:   avgConf,
			PredCount: predCount,
		})
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
			SpotLeadBps:     result.SpotLeadBps,
			SpotBarrierProb: result.SpotBarrierProb,
			MarketPrice:     result.MarketPrice,
			SpotPrice:       result.SpotPrice,
			SpotOpen:        result.SpotOpen,
			// Entry-gate thresholds (env-tuned) so the dashboard can show the
			// pass/fail of each condition and why a trade did/didn't fire.
			MinConf:         ss.minConfidence,
			MinEntryPrice:   ss.minEntryPrice,
			MaxEntryPrice:   ss.maxEntryPrice,
			MinEdge:         ss.minEdge,
			MaxRemaining:    ss.maxRemaining,
			// Sizing inputs.
			Balance:         ss.Engine.GetBalance(),
			BaseUSDC:        ss.GetDynamicPositionSize(),
			MaxExposureFrac: ss.maxMarketExposure,
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
		// Detect loss before clearing position metadata.
		entryPrice := ss.positionEntryPrice[marketID]
		isLoss := entryPrice > 0 && price < entryPrice

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

		if isLoss {
			log.Printf("[Sway] Loss detected on %s (sell %.4f < entry %.4f) — triggering retrain", marketID, price, entryPrice)
			go ss.triggerRetrain()
		}
	}

	if ss.dashboard != nil {
		ss.dashboard.RecordTrade(side, marketID, price, size)
		ss.dashboard.UpdatePosition(marketID, ss.ownedInventory[marketID], ss.marketExposure[marketID])
	}
}

// OnMarketWindowChange resets all per-window state when the 5-min window rolls over.
func (ss *SwayStrategy) OnMarketWindowChange() {
	ss.historyMu.Lock()
	ss.priceHistory = make(map[string][]priceTick)
	ss.historyMu.Unlock()

	ss.predMu.Lock()
	ss.predictions = make(map[string]*SwayPrediction)
	ss.predInFlight = make(map[string]bool)
	ss.lastPredSecond = make(map[string]int)
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

	if ss.dashboard != nil {
		ss.dashboard.SetRetraining(true)
	}

	go func() {
		defer func() {
			ss.retrainingMu.Lock()
			ss.retraining = false
			ss.retrainingMu.Unlock()
			if ss.dashboard != nil {
				ss.dashboard.SetRetraining(false)
			}
		}()

		log.Printf("[Sway] Retrain started (latest markets via %s)", ss.retrainScript)
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
