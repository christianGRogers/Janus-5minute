#!/usr/bin/env python3
"""
Cross-asset generalization test.

Applies the same strategies (sway baseline + spot/market fusion) to a DIFFERENT
asset's 5-minute up/down markets to check whether the edge is BTC-specific or a
general property of these markets. Each asset is trained and tested on its own
data (no cross-asset leakage).

Usage:
  python3 crossasset.py --asset eth
Saves cache/crossasset_<asset>.pkl.
"""

import os
import pickle
import argparse

import numpy as np

from datacache import load_dataset
from backtest_harness import evaluate
from models import MarketPriceStrategy, SwayBaseline, LogisticMicro
from models_spot import (
    attach_spot, SpotBarrier, CombinedLogistic, CombinedGBM, ConsensusStrategy,
)

_DIR = os.path.dirname(os.path.abspath(__file__))

# dataset name triples per asset
DATASETS = {
    "btc": ("train_set", "test_set", "val_set"),
    "eth": ("eth_train", "eth_test", "eth_val"),
    "sol": ("sol_train", "sol_test", "sol_val"),
}


def make_strategies():
    return [SwayBaseline(), MarketPriceStrategy(), LogisticMicro(),
            SpotBarrier(), CombinedLogistic(), CombinedGBM(), ConsensusStrategy()]


def run(asset):
    trn, tst, vl = DATASETS[asset]
    train = attach_spot(load_dataset(trn))
    test = attach_spot(load_dataset(tst))
    val = attach_spot(load_dataset(vl))
    print(f"[{asset}] train={len(train)} test={len(test)} val={len(val)} "
          f"(spot-matched)  test UP={np.mean([m['actual_bin'] for m in test]):.1%}")

    out = {}
    for s in make_strategies():
        s.fit(train)
        rt, rv = evaluate(s, test), evaluate(s, val)
        out[s.name] = {
            "test": {"roi": rt["trading"]["roi"], "n": rt["trading"]["n_bets"],
                     "acc": rt["overall"]["accuracy"], "win": rt["trading"]["win_rate"]},
            "val": {"roi": rv["trading"]["roi"], "n": rv["trading"]["n_bets"],
                    "acc": rv["overall"]["accuracy"], "win": rv["trading"]["win_rate"]},
        }

    with open(os.path.join(_DIR, "cache", f"crossasset_{asset}.pkl"), "wb") as f:
        pickle.dump(out, f)

    print(f"\n{asset.upper()}  {'Strategy':<18}{'testAcc':>8}{'testROI':>9}{'valROI':>9}{'min':>8}")
    print("-" * 62)
    for n in sorted(out, key=lambda n: -min(out[n]["test"]["roi"], out[n]["val"]["roi"])):
        t, v = out[n]["test"], out[n]["val"]
        print(f"{'':<6}{n:<18}{t['acc']:>8.1%}{t['roi']:>+9.1%}{v['roi']:>+9.1%}"
              f"{min(t['roi'], v['roi']):>+8.1%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="eth")
    args = ap.parse_args()
    run(args.asset)
