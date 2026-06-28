#!/usr/bin/env python3
"""
Three-window robustness check for the headline strategies.

Trains on train_set, evaluates trading ROI on THREE independent, time-disjoint
windows (test, val, oos3). A strategy profitable on all three is a genuine,
period-independent edge rather than a two-sample artifact.

Saves cache/robustness3.pkl for the report.
"""

import os
import pickle
import numpy as np

from datacache import load_dataset
from backtest_harness import evaluate
from models import MarketPriceStrategy, SwayBaseline, LogisticMicro, EdgeGBM
from models_spot import (
    attach_spot, SpotBarrier, SpotBarrierLate, SpotBarrierDrift,
    MarketTemperedBarrier, CombinedLogistic, CombinedGBM,
)

_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    train = attach_spot(load_dataset("train_set"))
    windows = {
        "test": attach_spot(load_dataset("test_set")),
        "val":  attach_spot(load_dataset("val_set")),
        "oos3": attach_spot(load_dataset("oos3_set")),
    }
    for w, d in windows.items():
        print(f"  {w}: {len(d)} markets, UP={np.mean([m['actual_bin'] for m in d]):.1%}")

    strategies = [
        SwayBaseline(), MarketPriceStrategy(), LogisticMicro(), EdgeGBM(),
        SpotBarrier(), SpotBarrierLate(max_remaining=20), SpotBarrierDrift(),
        MarketTemperedBarrier(w=0.5), CombinedLogistic(), CombinedGBM(),
    ]
    for s in strategies:
        s.fit(train)

    out = {}
    for s in strategies:
        out[s.name] = {}
        for w, d in windows.items():
            r = evaluate(s, d)
            out[s.name][w] = {"roi": r["trading"]["roi"],
                              "n_bets": r["trading"]["n_bets"],
                              "acc": r["overall"]["accuracy"],
                              "max_dd": r["trading"]["max_drawdown"],
                              "win": r["trading"]["win_rate"]}

    with open(os.path.join(_DIR, "cache", "robustness3.pkl"), "wb") as f:
        pickle.dump(out, f)

    wnames = list(windows.keys())
    print("\n" + "=" * 78)
    print(f"{'Strategy':<20}" + "".join(f"{w+' ROI':>11}" for w in wnames) + f"{'min ROI':>11}")
    print("-" * 78)
    order = sorted(out.keys(),
                   key=lambda n: -min(out[n][w]["roi"] for w in wnames))
    for n in order:
        rois = [out[n][w]["roi"] for w in wnames]
        line = f"{n:<20}" + "".join(f"{r:>+11.1%}" for r in rois) + f"{min(rois):>+11.1%}"
        print(line)
    print("\nSaved cache/robustness3.pkl")


if __name__ == "__main__":
    main()
