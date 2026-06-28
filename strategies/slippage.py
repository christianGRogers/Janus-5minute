#!/usr/bin/env python3
"""
Slippage / execution-cost sensitivity for the universal model.

Prediction markets are thin, so the edge must survive adverse execution. This
re-prices every bet with a worsened entry (entry price + slippage) and reports
ROI as slippage rises. Saves cache/slippage.pkl.
"""

import os
import pickle
import numpy as np

from datacache import load_dataset
from features_spot import extract_combined_features
from models_spot import attach_spot
from models import REMAINING_TIMES, LOOKUP_TOL

_DIR = os.path.dirname(os.path.abspath(__file__))
FEE = 0.072020
MARGIN = 0.03
SLIPS = [0.0, 0.005, 0.01, 0.02, 0.03, 0.05]
OOS = ["test_set", "val_set", "eth_test", "eth_val", "sol_test", "sol_val"]


def main():
    with open(os.path.join(_DIR, "combined_model_production.pkl"), "rb") as f:
        art = pickle.load(f)
    mdl, feats = art["model"], art["feature_names"]

    markets = []
    for a in OOS:
        markets += attach_spot(load_dataset(a))

    # precompute (q, p, outcome) per qualifying observation once
    sig = []
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
            sig.append((q, p, ab))

    res = {}
    for slip in SLIPS:
        prof = 0.0
        nb = 0
        for q, p, ab in sig:
            if q > p + MARGIN:
                pe = min(0.99, p + slip)
                prof += (1 / pe) * (1 if ab >= 0.5 else 0) - 1 - FEE * pe * (1 - pe)
                nb += 1
            elif q < p - MARGIN:
                dp = 1 - p
                de = min(0.99, dp + slip)
                prof += (1 / de) * (1 if ab < 0.5 else 0) - 1 - FEE * de * (1 - de)
                nb += 1
        res[slip] = {"roi": prof / nb if nb else 0.0, "n": nb}

    with open(os.path.join(_DIR, "cache", "slippage.pkl"), "wb") as f:
        pickle.dump({"results": res, "n_markets": len(markets)}, f)

    print(f"Pooled OOS markets: {len(markets)}")
    print(f"{'slippage':>10}{'ROI':>9}{'bets':>7}")
    for s in SLIPS:
        print(f"{s*100:>9.1f}%{res[s]['roi']:>+9.1%}{res[s]['n']:>7}")
    print("\nSaved cache/slippage.pkl")


if __name__ == "__main__":
    main()
