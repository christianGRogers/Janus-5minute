#!/usr/bin/env python3
"""
Universal (pooled) multi-asset model.

Instead of one model per asset, train a SINGLE model on BTC+ETH+SOL markets
pooled together, then test it on each asset. The features are asset-agnostic
(normalised bps / ratios / barrier probability), so a universal model should be
possible. If it matches per-asset models, one deployable model covers all
5-minute crypto markets.

Saves cache/pooled.pkl.
"""

import os
import pickle
import numpy as np

from datacache import load_dataset
from backtest_harness import evaluate
from models_spot import attach_spot, CombinedGBM, CombinedLogistic, ConsensusStrategy

_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS = ["btc", "eth", "sol"]
TRN = {"btc": "train_set", "eth": "eth_train", "sol": "sol_train"}
TST = {"btc": ("test_set", "val_set"), "eth": ("eth_test", "eth_val"),
       "sol": ("sol_test", "sol_val")}


def main():
    # pooled training data
    pooled = []
    per_asset_train = {}
    for a in ASSETS:
        d = attach_spot(load_dataset(TRN[a]))
        per_asset_train[a] = d
        pooled += d
    print(f"Pooled training markets: {len(pooled)} (btc+eth+sol)")

    eval_sets = {}
    for a in ASSETS:
        t, v = TST[a]
        eval_sets[a] = {"test": attach_spot(load_dataset(t)),
                        "val": attach_spot(load_dataset(v))}

    strat_classes = [CombinedGBM, CombinedLogistic, ConsensusStrategy]
    out = {}
    for cls in strat_classes:
        name = cls().name
        # pooled-trained
        sp = cls().fit(pooled)
        out[name] = {"pooled": {}, "perasset": {}}
        for a in ASSETS:
            rt = evaluate(sp, eval_sets[a]["test"])
            rv = evaluate(sp, eval_sets[a]["val"])
            out[name]["pooled"][a] = (rt["trading"]["roi"], rv["trading"]["roi"])
        # per-asset-trained (for comparison)
        for a in ASSETS:
            sa = cls().fit(per_asset_train[a])
            rt = evaluate(sa, eval_sets[a]["test"])
            rv = evaluate(sa, eval_sets[a]["val"])
            out[name]["perasset"][a] = (rt["trading"]["roi"], rv["trading"]["roi"])

    with open(os.path.join(_DIR, "cache", "pooled.pkl"), "wb") as f:
        pickle.dump(out, f)

    print(f"\n{'Strategy / asset':<22}{'POOLED test/val':>20}{'PER-ASSET test/val':>22}")
    print("-" * 66)
    for name in out:
        print(name)
        for a in ASSETS:
            pt, pv = out[name]["pooled"][a]
            at, av = out[name]["perasset"][a]
            print(f"  {a.upper():<18}{f'{pt:+.1%}/{pv:+.1%}':>22}{f'{at:+.1%}/{av:+.1%}':>22}")
    print("\nSaved cache/pooled.pkl")


if __name__ == "__main__":
    main()
