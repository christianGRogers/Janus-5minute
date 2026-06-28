# Strategy Research — BTC 5-Minute Up/Down

New prediction/trading strategies for the Polymarket BTC 5-minute up/down
markets, developed and benchmarked **against the existing Sway model**.

## TL;DR

| Finding | Detail |
|---|---|
| **Sway model is the weakest** | 77.4% accuracy, Brier 0.153 — far below every candidate and below just trusting the market price (89.0%). |
| **Sway loses money badly** | −27.3% trading ROI (−$243 over 890 bets). It bets the *most* because it diverges from the crowd price most often — and it is usually wrong. |
| **Trading ROI needs THREE windows to trust** | On 2 windows the spot-barrier models look like clear winners (+20% each). A 3rd, older window shows that edge is partly period-specific — it disappears there. |
| **Read the underlying BTC spot** | The market resolves on whether BTC closes up/down, so the Binance spot price (which the crowd prices imperfectly) is a powerful orthogonal signal — but it must be tempered with the crowd price, not trusted outright. |
| **Genuinely robust winners (positive on all 3 windows)** | `Combined-Logistic` **+13.5% / +22.6% / +8.1%** (regularised spot+market fusion) and `LogisticMicro` **+3.3% / +7.8% / +7.1%**. |
| **`SpotBarrier`** | Spectacular on 2 windows (+20%/+19%) but −1.5% on oos3 — the cautionary tale. |

The headline lesson: even two out-of-sample windows can mislead on trading P&L;
the **three-window** test is what separates a real edge from an artifact.

See **`STRATEGY_REPORT.pdf`** for the full comparison with charts.

## The key idea — spot first-passage / barrier pricing

A Polymarket 5-min market resolves UP iff BTC closes the window above its open.
At, say, 60s remaining the relevant question is a *digital-option* one: given the
current lead `L` over the open and realised per-second volatility `σ`, what is the
probability the window still closes UP?

```
P(UP) ≈ Φ( L / (σ · √t_remaining) )      # normal first-passage approximation
```

The crowd misprices this barrier probability (it over/under-reacts to the current
lead), so betting `SpotBarrier`'s estimate against the crowd price is profitable
and — unlike the ML models — **robust across both test windows**.

## Why the Sway model is weak

The sway model fits a linear "channel" to the UP-token price series and uses
only `slope / width` ratios. **It deliberately discards the absolute price
level** — which on a prediction market *is* the crowd's probability estimate and
the single most predictive feature. Candidate strategies here keep the price
level plus VWAP, multi-horizon momentum/volatility, and order-flow imbalance.

## Pipeline

```
datacache.py        # fetch + locally cache Polymarket trade data (concurrent, retrying)
spotcache.py        # fetch + cache Binance BTCUSDT 1s klines per market window
features.py         # no-look-ahead prediction-market features (rich + faithful sway)
features_spot.py    # no-look-ahead spot features (lead, vol, first-passage barrier prob)
models.py           # prediction-market strategies + the Sway baseline
models_spot.py      # spot-driven strategies (SpotBarrier, Combined-*, etc.)
backtest_harness.py # train all on train_set, evaluate on test_set, P&L sim
validate.py         # cross-window robustness: evaluate on test AND val windows
make_report.py      # render STRATEGY_REPORT.pdf
```

### Reproduce

```bash
cd strategies
python3 datacache.py --name train_set --n 600 --offset 290   # older markets
python3 datacache.py --name test_set  --n 250 --offset 3     # recent markets
python3 backtest_harness.py
python3 make_report.py
```

Data is cached under `cache/` so re-runs are instant. Train and test sets are
**time-disjoint** (train on older markets, test on more recent) — realistic
train-on-past / predict-future evaluation with no look-ahead.

## Strategies

- **MarketPrice** — predict the current UP-token price (crowd consensus).
- **Momentum** — market price nudged by short-horizon momentum + flow.
- **Sway (baseline)** — faithful reproduction of the repo's per-slot
  GradientBoosting model on the 29 channel-sway features.
- **LogisticMicro / GBM-Rich / RF-Rich / XGB-Rich / LGBM-Rich** — classifiers on
  the rich feature set predicting the binary outcome.
- **Edge-GBM / Edge-Ridge** — regress the *crowd's error* (`outcome − price`);
  bet only where the market is predicted to be mispriced.
- **XGB-Calibrated** — isotonic-calibrated XGBoost for cleaner EV decisions.
- **Ensemble** — blend of the strongest members, shrunk toward the crowd price.

## Metrics

- **Statistical**: directional accuracy, Brier score, log-loss (per remaining
  slot 60/30/20/15/10s and overall).
- **Trading**: fee-aware Polymarket P&L simulation that only places a $1 bet when
  a model's probability diverges from the live price by enough for positive
  expected value (default 3% margin). Reports ROI, win rate, max drawdown, and a
  margin-sensitivity sweep.
