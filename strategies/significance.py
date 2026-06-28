#!/usr/bin/env python3
"""
Statistical significance of the universal model's edge, on CLEAN out-of-sample
data only.

The production model is trained on the *_test and *_train sets, so only the
*_val windows are genuinely held out from it. We bootstrap the per-bet returns
on those val windows to get a 95% CI and a one-sided p-value. Saves
cache/significance.pkl.
"""

import os
import pickle
from math import sqrt

import numpy as np

from datacache import load_dataset
from features_spot import extract_combined_features
from models_spot import attach_spot
from models import REMAINING_TIMES, LOOKUP_TOL

_DIR = os.path.dirname(os.path.abspath(__file__))
FEE = 0.072020
MARGIN = 0.03
CLEAN_OOS = ["val_set", "eth_val", "sol_val"]   # never used to train production model


def main():
    with open(os.path.join(_DIR, "combined_model_production.pkl"), "rb") as f:
        art = pickle.load(f)
    mdl, feats = art["model"], art["feature_names"]

    markets = []
    for a in CLEAN_OOS:
        markets += attach_spot(load_dataset(a))

    profits = []
    for m in markets:
        relmax = (m["times"] - m["market_start"]).max() if len(m["times"]) else -1
        ab = m["actual_bin"]
        for rem in REMAINING_TIMES:
            e = 300 - rem
            if relmax < e - LOOKUP_TOL:
                continue
            f = extract_combined_features(m, e)
            if f is None:
                continue
            x = np.nan_to_num(np.array([[f.get(k, 0.0) for k in feats]]))
            q = float(np.clip(mdl.predict_proba(x)[0, 1], 0, 1))
            p = float(np.clip(f["last_price"], 0.01, 0.99))
            if q > p + MARGIN:
                profits.append((1 / p) * (1 if ab >= 0.5 else 0) - 1 - FEE * p * (1 - p))
            elif q < p - MARGIN:
                dp = 1 - p
                profits.append((1 / dp) * (1 if ab < 0.5 else 0) - 1 - FEE * dp * (1 - dp))

    profits = np.array(profits)
    n = len(profits)
    mean = float(profits.mean())
    rng = np.random.default_rng(42)
    boot = np.array([profits[rng.integers(0, n, n)].mean() for _ in range(5000)])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    res = {"n_bets": n, "mean_roi": mean, "ci_lo": float(lo), "ci_hi": float(hi),
           "p_le_0": float((boot <= 0).mean()),
           "t_stat": float(mean / (profits.std() / sqrt(n)))}
    with open(os.path.join(_DIR, "cache", "significance.pkl"), "wb") as f:
        pickle.dump(res, f)

    print("CLEAN OOS (val windows only, never in production training)")
    print(f"{n} bets | mean ROI/bet {mean:+.2%} | 95% CI [{lo:+.2%}, {hi:+.2%}] | "
          f"P(<=0)={res['p_le_0']:.4f} | t={res['t_stat']:.2f}")
    print("Saved cache/significance.pkl")


if __name__ == "__main__":
    main()
