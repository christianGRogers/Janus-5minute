#!/usr/bin/env python3
"""
Zero-shot cross-asset transfer.

Take the shipped universal model (combined_model_production.pkl, trained ONLY on
BTC+ETH+SOL) and evaluate it, with NO retraining, on assets it has never seen:
XRP, DOGE, BNB. If it is still profitable, the edge transfers zero-shot to new
markets — the strongest possible generalization claim.

Saves cache/zeroshot.pkl.
"""

import os
import pickle
import numpy as np

from datacache import load_dataset
from backtest_harness import evaluate
from models_spot import attach_spot
from features_spot import extract_combined_features

_DIR = os.path.dirname(os.path.abspath(__file__))
UNSEEN = ["xrp", "doge", "bnb"]


class FrozenUniversal:
    """Wrap the saved production artifact as a no-retrain strategy."""
    name = "Universal (zero-shot)"

    def __init__(self):
        with open(os.path.join(_DIR, "combined_model_production.pkl"), "rb") as f:
            art = pickle.load(f)
        self.model = art["model"]
        self.feature_names = art["feature_names"]

    def fit(self, markets):
        return self  # frozen

    def predict(self, market, elapsed, remaining):
        f = extract_combined_features(market, elapsed)
        if f is None:
            return None
        x = np.nan_to_num(np.array([[f.get(k, 0.0) for k in self.feature_names]], dtype=float))
        return float(np.clip(self.model.predict_proba(x)[0, 1], 0.0, 1.0))


def main():
    model = FrozenUniversal()
    out = {}
    for a in UNSEEN:
        test = attach_spot(load_dataset(f"{a}_test"))
        val = attach_spot(load_dataset(f"{a}_val"))
        rt, rv = evaluate(model, test), evaluate(model, val)
        out[a] = {
            "test": {"roi": rt["trading"]["roi"], "acc": rt["overall"]["accuracy"],
                     "n": rt["trading"]["n_bets"], "win": rt["trading"]["win_rate"]},
            "val": {"roi": rv["trading"]["roi"], "acc": rv["overall"]["accuracy"],
                    "n": rv["trading"]["n_bets"], "win": rv["trading"]["win_rate"]},
        }

    with open(os.path.join(_DIR, "cache", "zeroshot.pkl"), "wb") as f:
        pickle.dump(out, f)

    print(f"{'Unseen asset':<14}{'testAcc':>9}{'testROI':>9}{'valROI':>9}{'testWin':>9}")
    print("-" * 50)
    for a in UNSEEN:
        t, v = out[a]["test"], out[a]["val"]
        print(f"{a.upper():<14}{t['acc']:>9.1%}{t['roi']:>+9.1%}{v['roi']:>+9.1%}{t['win']:>9.1%}")
    print("\nSaved cache/zeroshot.pkl")


if __name__ == "__main__":
    main()
