#!/usr/bin/env python3
"""
Robustness check: retrain all strategies on train_set, then evaluate each on
TWO independent, time-disjoint held-out windows:
  - test_set : recent markets (offset ~3-250)
  - val_set  : older markets  (offset ~1000+), fully disjoint from train & test

If a strategy's ranking holds across both windows, the result is not a fluke of
one sample. Saves cache/validation.pkl for the report.
"""

import os
import pickle
import time
import numpy as np

from datacache import load_dataset
from backtest_harness import evaluate
from models import (
    MarketPriceStrategy, MomentumStrategy, SwayBaseline,
    LogisticMicro, GBMRich, RandomForestRich, XGBRich, LGBMRich,
    EdgeGBM, EdgeRidge, CalibratedXGB, TimeSlotLogistic, CalibratedLogistic,
    BlendStrategy,
)

_DIR = os.path.dirname(os.path.abspath(__file__))


def build_strategies(train):
    strategies = [
        MarketPriceStrategy(), MomentumStrategy(k=0.5), SwayBaseline(),
        LogisticMicro(), TimeSlotLogistic(), CalibratedLogistic(),
        GBMRich(), RandomForestRich(), XGBRich(), LGBMRich(),
        EdgeGBM(), EdgeRidge(), CalibratedXGB(),
    ]
    fitted = []
    for s in strategies:
        t0 = time.time()
        print(f"  fit {s.name}...", end=" ", flush=True)
        s.fit(train)
        print(f"{time.time()-t0:.1f}s")
        fitted.append(s)
    blend = BlendStrategy(
        members=[LogisticMicro().fit(train), EdgeGBM().fit(train),
                 CalibratedXGB().fit(train), MarketPriceStrategy()],
        weights=[1.3, 1.0, 1.0, 1.0], shrink=0.10, name="Ensemble")
    fitted.append(blend)
    return fitted


def main():
    print("Loading datasets...")
    train = load_dataset("train_set")
    test = load_dataset("test_set")
    val = load_dataset("val_set")
    print(f"  train={len(train)} test={len(test)} val={len(val)}")
    print(f"  test UP={np.mean([m['actual_bin'] for m in test]):.1%}  "
          f"val UP={np.mean([m['actual_bin'] for m in val]):.1%}")

    print("\nTraining strategies on train_set...")
    fitted = build_strategies(train)

    windows = {"test": test, "val": val}
    out = {"windows": {}, "meta": {
        "n_train": len(train), "n_test": len(test), "n_val": len(val),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}}

    for wname, wdata in windows.items():
        print(f"\nEvaluating on {wname} ({len(wdata)} markets)...")
        res = {}
        for s in fitted:
            res[s.name] = evaluate(s, wdata)
            ov, tr = res[s.name]["overall"], res[s.name]["trading"]
            print(f"  {s.name:<18} acc={ov['accuracy']:.1%} brier={ov['brier']:.4f} "
                  f"ROI={tr['roi']:+.1%} (bets={tr['n_bets']})")
        out["windows"][wname] = res

    with open(os.path.join(_DIR, "cache", "validation.pkl"), "wb") as f:
        pickle.dump(out, f)
    print("\nSaved cache/validation.pkl")

    # Side-by-side summary
    print("\n" + "=" * 74)
    print(f"{'Strategy':<18}{'test acc':>9}{'val acc':>9}{'test ROI':>10}{'val ROI':>10}")
    print("-" * 74)
    names = sorted(out["windows"]["test"].keys(),
                   key=lambda n: -out["windows"]["test"][n]["trading"]["roi"])
    for n in names:
        t = out["windows"]["test"][n]
        v = out["windows"]["val"][n]
        print(f"{n:<18}{t['overall']['accuracy']:>9.1%}{v['overall']['accuracy']:>9.1%}"
              f"{t['trading']['roi']:>+10.1%}{v['trading']['roi']:>+10.1%}")


if __name__ == "__main__":
    main()
