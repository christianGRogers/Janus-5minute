#!/usr/bin/env python3
"""
Realistic walk-forward evaluation.

The live bot (retrain.py) retrains on the latest ~600 markets. The earlier
robustness test trained ONCE on a single period and applied it to three very
different periods — a deliberately harsh stress test. Here instead each window is
evaluated with a model trained on the 600 markets IMMEDIATELY PRECEDING it, which
mirrors production. This isolates "is the edge real when freshly trained?" from
"does a stale model transfer across periods?".

  window  trained on (preceding 600 markets)
  test    train_set        (offset ~291-891)
  val     trainval_set     (offset ~1338-1938)
  oos3    trainoos3_set    (offset ~2016-2616)

Saves cache/walkforward.pkl.
"""

import os
import pickle
import numpy as np

from datacache import load_dataset
from backtest_harness import evaluate
from models import MarketPriceStrategy, SwayBaseline, LogisticMicro
from models_spot import (
    attach_spot, SpotBarrier, MarketTemperedBarrier, CombinedLogistic, CombinedGBM,
)

_DIR = os.path.dirname(os.path.abspath(__file__))


def make_strategies():
    return [SwayBaseline(), MarketPriceStrategy(), LogisticMicro(),
            SpotBarrier(), MarketTemperedBarrier(w=0.5),
            CombinedLogistic(), CombinedGBM()]


def main():
    pairs = {
        "test": ("train_set", "test_set"),
        "val":  ("trainval_set", "val_set"),
        "oos3": ("trainoos3_set", "oos3_set"),
    }

    out = {}            # strategy -> window -> roi/acc
    for wname, (trn, tst) in pairs.items():
        train = attach_spot(load_dataset(trn))
        test = attach_spot(load_dataset(tst))
        print(f"[{wname}] train={len(train)} ({trn})  eval={len(test)} ({tst})")
        strategies = make_strategies()
        for s in strategies:
            s.fit(train)
            r = evaluate(s, test)
            out.setdefault(s.name, {})[wname] = {
                "roi": r["trading"]["roi"], "n_bets": r["trading"]["n_bets"],
                "acc": r["overall"]["accuracy"]}

    with open(os.path.join(_DIR, "cache", "walkforward.pkl"), "wb") as f:
        pickle.dump(out, f)

    wn = list(pairs.keys())
    print(f"\n{'Strategy':<20}" + "".join(f"{w+' ROI':>11}" for w in wn) + f"{'min':>11}")
    print("-" * 75)
    for n in sorted(out, key=lambda n: -min(out[n][w]["roi"] for w in wn)):
        rois = [out[n][w]["roi"] for w in wn]
        print(f"{n:<20}" + "".join(f"{r:>+11.1%}" for r in rois) + f"{min(rois):>+11.1%}")
    print("\nSaved cache/walkforward.pkl")


if __name__ == "__main__":
    main()
