#!/usr/bin/env python3
"""
Bankroll / position-sizing simulation.

Per-bet ROI ignores compounding and risk. Here each strategy plays its bets in
chronological order with fractional-Kelly sizing and a starting bankroll, so we
can compare realised bankroll growth and drawdown — the numbers that matter for
actually deploying a strategy.

Kelly fraction for a binary Polymarket bet:
  buy UP at price p, model prob q:  f = (q - p) / (1 - p)
  buy DOWN at (1-p), model prob q:  f = (p - q) / p
We use a fractional multiplier (default 0.25x Kelly) and a per-bet cap to keep
variance sane. Fees use the Polymarket formula.

Saves cache/kelly.pkl for the report.
"""

import os
import pickle
import numpy as np

from datacache import load_dataset
from features import extract_features
from models import REMAINING_TIMES, LOOKUP_TOL, MarketPriceStrategy, SwayBaseline, LogisticMicro
from models_spot import attach_spot, SpotBarrier, CombinedLogistic, MarketTemperedBarrier

_DIR = os.path.dirname(os.path.abspath(__file__))
FEE_COEF = 0.072020
EV_MARGIN = 0.03
KELLY_FRAC = 0.10     # fractional Kelly (conservative — edge is noisy)
MAX_BET_FRAC = 0.02   # never stake more than 2% of bankroll on one bet
START_BANKROLL = 1000.0


def simulate(strategy, markets):
    """Chronological fractional-Kelly bankroll path over one window."""
    # collect bets in chronological order
    bets = []
    for m in markets:
        rel_max = (m["times"] - m["market_start"]).max() if len(m["times"]) else -1
        for remaining in REMAINING_TIMES:
            elapsed = 300 - remaining
            if rel_max < elapsed - LOOKUP_TOL:
                continue
            q = strategy.predict(m, elapsed, remaining)
            if q is None:
                continue
            feat = extract_features(m, elapsed)
            if feat is None:
                continue
            p = float(np.clip(feat["last_price"], 0.01, 0.99))
            # bet time = market_start + elapsed (when the decision is made)
            bets.append((m["market_start"] + elapsed, q, p, m["actual_bin"]))
    bets.sort(key=lambda b: b[0])

    bankroll = START_BANKROLL
    curve = [bankroll]
    peak = bankroll
    max_dd = 0.0
    n_bets = 0
    for _, q, p, ab in bets:
        if q > p + EV_MARGIN:                      # buy UP
            f = (q - p) / (1 - p)
            stake = min(MAX_BET_FRAC, max(0.0, f) * KELLY_FRAC) * bankroll
            if stake <= 0:
                continue
            fee = stake * FEE_COEF * p * (1 - p)
            won = ab >= 0.5
            pnl = stake * ((1.0 / p - 1.0) if won else -1.0) - fee
        elif q < p - EV_MARGIN:                    # buy DOWN
            dp = 1 - p
            f = (p - q) / p
            stake = min(MAX_BET_FRAC, max(0.0, f) * KELLY_FRAC) * bankroll
            if stake <= 0:
                continue
            fee = stake * FEE_COEF * dp * (1 - dp)
            won = ab < 0.5
            pnl = stake * ((1.0 / dp - 1.0) if won else -1.0) - fee
        else:
            continue
        bankroll += pnl
        n_bets += 1
        curve.append(bankroll)
        peak = max(peak, bankroll)
        max_dd = max(max_dd, (peak - bankroll) / peak)
        if bankroll <= 1.0:
            break
    return {"final": bankroll, "mult": bankroll / START_BANKROLL,
            "max_dd_pct": max_dd, "n_bets": n_bets, "curve": curve}


def main():
    train = attach_spot(load_dataset("train_set"))
    windows = {
        "test": attach_spot(load_dataset("test_set")),
        "val":  attach_spot(load_dataset("val_set")),
        "oos3": attach_spot(load_dataset("oos3_set")),
    }
    strategies = [
        CombinedLogistic(), LogisticMicro(), MarketTemperedBarrier(w=0.5),
        SpotBarrier(), SwayBaseline(), MarketPriceStrategy(),
    ]
    for s in strategies:
        s.fit(train)

    out = {}
    for s in strategies:
        out[s.name] = {w: simulate(s, d) for w, d in windows.items()}

    with open(os.path.join(_DIR, "cache", "kelly.pkl"), "wb") as f:
        pickle.dump({"results": out, "params": {
            "kelly_frac": KELLY_FRAC, "max_bet_frac": MAX_BET_FRAC,
            "start": START_BANKROLL, "ev_margin": EV_MARGIN}}, f)

    wn = list(windows.keys())
    print(f"\n{'Strategy':<22}" + "".join(f"{w+' x':>10}" for w in wn)
          + f"{'minDD%':>9}")
    print("-" * 64)
    order = sorted(out.keys(), key=lambda n: -min(out[n][w]["mult"] for w in wn))
    for n in order:
        mults = [out[n][w]["mult"] for w in wn]
        worst_dd = max(out[n][w]["max_dd_pct"] for w in wn)
        print(f"{n:<22}" + "".join(f"{mlt:>9.2f}x" for mlt in mults)
              + f"{worst_dd*100:>8.0f}%")
    print(f"\n({KELLY_FRAC}x Kelly, {MAX_BET_FRAC:.0%} bet cap, "
          f"${START_BANKROLL:.0f} start)  Saved cache/kelly.pkl")


if __name__ == "__main__":
    main()
