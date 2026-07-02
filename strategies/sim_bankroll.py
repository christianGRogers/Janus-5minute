#!/usr/bin/env python3
"""
Realistic bankroll simulation of the LIVE bot over a sequence of markets.

Mirrors pkg/strategies/sway.go behavior:
  - predict at 30/20/15/10s remaining (live only trades <=30s)
  - confidence gate (>=0.85), positive-EV divergence gate (>3%)
  - fractional sizing: stake = balance * RiskTolerance(0.20) * confScale,
    capped at 35% market exposure; min 0.5 shares
  - pays the ASK (entry = price + spread), Polymarket fee
Starts at $10, runs chronologically, reports P&L across spread assumptions.
"""

import sys
import numpy as np
import pickle

from datacache import load_dataset
from features_spot import extract_combined_features
from models_spot import attach_spot
from models import LOOKUP_TOL

FEE = 0.072020
MARGIN = 0.05        # SWAY_MIN_EDGE
MIN_CONF = 0.20      # SWAY_MIN_CONF
MAX_PRICE = 0.80     # SWAY_MAX_PRICE
MIN_PRICE = 0.50     # SWAY_MIN_PRICE — skip contrarian "wrong side" longshots
RISK_TOL = 0.20
MAX_EXPOSURE = 0.35
START = 10.0
SLOTS = [60, 30, 20, 15, 10]   # SWAY_MAX_REMAINING=60


def load_model():
    with open("combined_model_production.pkl", "rb") as f:
        return pickle.load(f)


def precompute(markets, mdl, feats):
    """Per market: chronological list of (slot, q, p) signals that pass the gates."""
    out = []
    for m in markets:
        relmax = (m["times"] - m["market_start"]).max() if len(m["times"]) else -1
        sigs = []
        for rem in SLOTS:
            e = 300 - rem
            if relmax < e - LOOKUP_TOL:
                continue
            f = extract_combined_features(m, e)
            if f is None:
                continue
            x = np.nan_to_num(np.array([[f.get(k, 0.0) for k in feats]]))
            q = float(np.clip(mdl.predict_proba(x)[0, 1], 0, 1))
            p = float(np.clip(f["last_price"], 0.01, 0.99))
            sigs.append((q, p))
        out.append({"start": m["market_start"], "ab": m["actual_bin"], "sigs": sigs})
    out.sort(key=lambda d: d["start"])
    return out


def run(seq, spread):
    bal = START
    peak = bal
    maxdd = 0.0
    nbets = 0
    wins = 0
    fees = 0.0
    for mk in seq:
        ab = mk["ab"]
        exposure = 0.0
        for q, p in mk["sigs"]:
            conf = abs(q - 0.5) * 2
            if conf < MIN_CONF:
                continue
            side = None
            if q > p + MARGIN:
                side = "UP"
            elif q < p - MARGIN:
                side = "DOWN"
            else:
                continue
            base_price = p if side == "UP" else (1 - p)
            if base_price > MAX_PRICE:      # skip negative-skew near-resolution bets
                continue
            if base_price < MIN_PRICE:      # skip contrarian "wrong side" longshots
                continue
            confScale = min(1.0, (conf - MIN_CONF) / (1.0 - MIN_CONF) + 0.5)
            cap = MAX_EXPOSURE * bal - exposure
            stake = min(bal * RISK_TOL * confScale, cap)
            if stake <= 0:
                continue
            entry = min(0.99, max(0.01, base_price + spread))
            if stake / entry < 0.5:   # min 0.5 shares
                continue
            won = (ab >= 0.5) if side == "UP" else (ab < 0.5)
            fee = stake * FEE * entry * (1 - entry)
            pnl = stake * ((1.0 / entry - 1.0) if won else -1.0) - fee
            bal += pnl
            exposure += stake
            fees += fee
            nbets += 1
            wins += int(won)
            peak = max(peak, bal)
            if bal > 0:
                maxdd = max(maxdd, (peak - bal) / peak)
            if bal <= 0.5:
                return {"final": max(bal, 0), "nbets": nbets, "wins": wins,
                        "maxdd": maxdd, "fees": fees, "ruin": True}
    return {"final": bal, "nbets": nbets, "wins": wins, "maxdd": maxdd,
            "fees": fees, "ruin": False}


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "sim1k_btc"
    md = load_model()
    mdl, feats = md["model"], md["feature_names"]
    markets = attach_spot(load_dataset(name))
    print(f"Markets: {len(markets)} ({name})  | start ${START:.0f}  | model trained {md['metadata'].get('training_date')}")
    seq = precompute(markets, mdl, feats)
    hours = len(seq) * 5 / 60.0
    print(f"Horizon: {len(seq)} markets x 5min = {hours:.0f}h (~{hours/24:.1f} days) of one-asset trading\n")

    print(f"{'spread':>8}{'final $':>10}{'P&L $':>9}{'ROI%':>8}{'bets':>7}{'win%':>7}{'maxDD':>7}{'fees$':>8}")
    base = None
    for spread in [0.0, 0.02, 0.04, 0.06]:
        r = run(seq, spread)
        pnl = r["final"] - START
        wr = r["wins"] / r["nbets"] if r["nbets"] else 0
        tag = "  <-RUIN" if r["ruin"] else ""
        print(f"{spread*100:>7.0f}%{r['final']:>10.2f}{pnl:>+9.2f}{pnl/START*100:>+7.0f}%"
              f"{r['nbets']:>7}{wr:>7.1%}{r['maxdd']:>7.0%}{r['fees']:>8.2f}{tag}")
        if spread == 0.04:
            base = r
    # order-robustness: shuffle market order to get a P&L range at a realistic 4% spread
    rng = np.random.default_rng(0)
    finals = []
    for _ in range(300):
        rng.shuffle(seq)
        finals.append(run(seq, 0.04)["final"])
    finals = np.array(finals)
    print(f"\nAt 4% spread, P&L range over 300 shuffles of market order:")
    print(f"  median final ${np.median(finals):.2f}  (P&L ${np.median(finals)-START:+.2f})"
          f"  | 5th–95th: ${np.percentile(finals,5):.2f}–${np.percentile(finals,95):.2f}"
          f"  | ruin {np.mean(finals<=0.5):.0%}")


if __name__ == "__main__":
    main()
