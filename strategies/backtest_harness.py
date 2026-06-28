#!/usr/bin/env python3
"""
Unified backtest harness.

Trains every strategy on the SAME train set and evaluates each on the SAME
held-out test set, producing:
  - statistical metrics: accuracy, Brier, log-loss (per slot + overall)
  - trading metrics: a realistic Polymarket P&L simulation that only bets when
    the model's probability diverges from the market price enough for positive
    expected value (with fees).

Results are pickled to cache/results.pkl for the report generator.
"""

import os
import pickle
import time
import numpy as np

from datacache import load_dataset
from features import extract_features
from models import (
    REMAINING_TIMES, LOOKUP_TOL,
    MarketPriceStrategy, MomentumStrategy, SwayBaseline,
    LogisticMicro, GBMRich, RandomForestRich, XGBRich, LGBMRich, BlendStrategy,
    EdgeGBM, EdgeRidge, CalibratedXGB,
)

_DIR = os.path.dirname(os.path.abspath(__file__))

# Polymarket fee model (per README): fee = size * 0.072020 * p * (1-p)
FEE_COEF = 0.072020
EV_MARGIN = 0.03      # only bet when |p - price| edge clears this
BET_SIZE = 1.0        # $1 per qualifying signal


def _logloss(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def evaluate(strategy, test_markets):
    """Return dict of per-slot + overall stats and trading P&L for one strategy."""
    slots = {r: {"correct": 0, "brier": 0.0, "ll": 0.0, "n": 0} for r in REMAINING_TIMES}

    trades = []   # each: dict(profit, won, side, price, remaining)
    signals = []  # raw per-observation (p, price, actual_bin, remaining) for margin sweeps

    for m in test_markets:
        times = m["times"]
        rel_max = (times - m["market_start"]).max() if len(times) else -1
        actual_bin = m["actual_bin"]
        for remaining in REMAINING_TIMES:
            elapsed = 300 - remaining
            if rel_max < elapsed - LOOKUP_TOL:
                continue
            p = strategy.predict(m, elapsed, remaining)
            if p is None:
                continue
            s = slots[remaining]
            s["n"] += 1
            s["correct"] += int((p >= 0.5) == (actual_bin >= 0.5))
            s["brier"] += (p - actual_bin) ** 2
            s["ll"] += _logloss(p, actual_bin)

            # --- trading simulation ---
            feat = extract_features(m, elapsed)
            if feat is None:
                continue
            price = float(np.clip(feat["last_price"], 0.01, 0.99))
            signals.append((float(p), price, float(actual_bin), int(remaining)))
            # Expected value of betting each side using model prob p
            # bet UP at `price`: EV = p/price - 1 ; bet DOWN at (1-price): EV=(1-p)/(1-price)-1
            if p > price + EV_MARGIN:
                # buy UP
                shares = BET_SIZE / price
                fee = BET_SIZE * FEE_COEF * price * (1 - price)
                won = actual_bin >= 0.5
                payout = shares * (1.0 if won else 0.0)
                profit = payout - BET_SIZE - fee
                trades.append({"profit": profit, "won": won, "side": "UP",
                               "price": price, "remaining": remaining})
            elif p < price - EV_MARGIN:
                # buy DOWN at (1-price)
                dprice = 1 - price
                shares = BET_SIZE / dprice
                fee = BET_SIZE * FEE_COEF * dprice * (1 - dprice)
                won = actual_bin < 0.5
                payout = shares * (1.0 if won else 0.0)
                profit = payout - BET_SIZE - fee
                trades.append({"profit": profit, "won": won, "side": "DOWN",
                               "price": dprice, "remaining": remaining})

    # aggregate stats
    res = {"slots": {}, "name": strategy.name}
    tot_c = tot_n = 0
    tot_b = tot_l = 0.0
    for r in REMAINING_TIMES:
        s = slots[r]
        if s["n"] > 0:
            res["slots"][r] = {
                "accuracy": s["correct"] / s["n"],
                "brier": s["brier"] / s["n"],
                "logloss": s["ll"] / s["n"],
                "n": s["n"],
            }
        tot_c += s["correct"]; tot_n += s["n"]
        tot_b += s["brier"]; tot_l += s["ll"]
    res["overall"] = {
        "accuracy": tot_c / tot_n if tot_n else 0.0,
        "brier": tot_b / tot_n if tot_n else 1.0,
        "logloss": tot_l / tot_n if tot_n else 1.0,
        "n": tot_n,
    }

    # trading aggregate
    if trades:
        profits = np.array([t["profit"] for t in trades])
        wins = np.array([t["won"] for t in trades])
        n_bets = len(trades)
        total_profit = float(profits.sum())
        staked = n_bets * BET_SIZE
        # equity curve for drawdown
        eq = np.cumsum(profits)
        peak = np.maximum.accumulate(eq)
        max_dd = float((peak - eq).max()) if n_bets else 0.0
        res["trading"] = {
            "n_bets": n_bets,
            "total_profit": total_profit,
            "roi": total_profit / staked if staked else 0.0,
            "win_rate": float(wins.mean()),
            "avg_profit": float(profits.mean()),
            "max_drawdown": max_dd,
            "sharpe": float(profits.mean() / profits.std()) if profits.std() > 1e-9 else 0.0,
            "equity_curve": eq.tolist(),
        }
    else:
        res["trading"] = {"n_bets": 0, "total_profit": 0.0, "roi": 0.0,
                          "win_rate": 0.0, "avg_profit": 0.0, "max_drawdown": 0.0,
                          "sharpe": 0.0, "equity_curve": []}

    # ROI across a sweep of EV margins (recomputed from raw signals)
    res["margin_sweep"] = {}
    for mg in (0.02, 0.03, 0.05, 0.08, 0.12):
        prof, nb = 0.0, 0
        for p, price, ab, _ in signals:
            if p > price + mg:
                prof += (BET_SIZE / price) * (1.0 if ab >= 0.5 else 0.0) - BET_SIZE \
                        - BET_SIZE * FEE_COEF * price * (1 - price)
                nb += 1
            elif p < price - mg:
                dp = 1 - price
                prof += (BET_SIZE / dp) * (1.0 if ab < 0.5 else 0.0) - BET_SIZE \
                        - BET_SIZE * FEE_COEF * dp * (1 - dp)
                nb += 1
        res["margin_sweep"][mg] = {"roi": prof / (nb * BET_SIZE) if nb else 0.0,
                                    "n_bets": nb, "profit": prof}
    return res


def main():
    print("Loading datasets...")
    train = load_dataset("train_set")
    test = load_dataset("test_set")
    print(f"  train: {len(train)} markets  |  test: {len(test)} markets")
    base_rate = np.mean([m["actual_bin"] for m in test])
    print(f"  test base rate (UP): {base_rate:.1%}")

    strategies = [
        MarketPriceStrategy(),
        MomentumStrategy(k=0.5),
        SwayBaseline(),
        LogisticMicro(),
        GBMRich(),
        RandomForestRich(),
        XGBRich(),
        LGBMRich(),
        EdgeGBM(),
        EdgeRidge(),
        CalibratedXGB(),
    ]

    # Train base strategies
    fitted = []
    for s in strategies:
        t0 = time.time()
        print(f"Training {s.name}...", end=" ", flush=True)
        s.fit(train)
        print(f"done ({time.time()-t0:.1f}s)")
        fitted.append(s)

    # Ensemble: blend the profitable LogisticMicro + edge model + calibrated XGB,
    # shrunk lightly toward the crowd price for stability.
    blend = BlendStrategy(
        members=[LogisticMicro().fit(train), EdgeGBM().fit(train),
                 CalibratedXGB().fit(train), MarketPriceStrategy()],
        weights=[1.3, 1.0, 1.0, 1.0],
        shrink=0.10,
        name="Ensemble",
    )
    fitted.append(blend)

    # Evaluate all
    results = {}
    for s in fitted:
        t0 = time.time()
        print(f"Evaluating {s.name}...", end=" ", flush=True)
        results[s.name] = evaluate(s, test)
        ov = results[s.name]["overall"]
        tr = results[s.name]["trading"]
        print(f"acc={ov['accuracy']:.1%} brier={ov['brier']:.4f} "
              f"ll={ov['logloss']:.4f} | bets={tr['n_bets']} "
              f"ROI={tr['roi']:+.1%} P&L=${tr['total_profit']:+.2f} "
              f"({time.time()-t0:.1f}s)")

    meta = {
        "n_train": len(train), "n_test": len(test),
        "base_rate_up": float(base_rate),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "ev_margin": EV_MARGIN, "fee_coef": FEE_COEF,
    }
    with open(os.path.join(_DIR, "cache", "results.pkl"), "wb") as f:
        pickle.dump({"results": results, "meta": meta}, f)
    print("\nSaved results to cache/results.pkl")


if __name__ == "__main__":
    main()
