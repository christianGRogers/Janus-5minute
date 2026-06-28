#!/usr/bin/env python3
"""
Production retrainer for the universal Combined-GBM model.

Mirrors sway_model/retrain.py but for the spot+market fusion model: fetches the
latest markets for the configured asset(s), pulls their Binance 1s spot, trains
Combined-GBM, and atomically writes combined_model_production.pkl so a mid-train
prediction never reads a half-written file.

Invoked by the Go bot with no arguments (same contract as retrain.py).

Env:
  SWAY_ASSET            comma-separated assets to train on (default "btc")
  RETRAIN_MARKETS       markets per asset to fetch (default 600)
"""

import os
import sys
import time
import pickle
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import numpy as np

from datacache import fetch_market
from spotcache import fetch_spot, symbol_for
from features_spot import extract_combined_features
from models import build_training_table

OUTPUT = os.path.join(_DIR, "combined_model_production.pkl")
RETRAIN_MARKETS = int(os.getenv("RETRAIN_MARKETS", "600"))
ASSETS = [a.strip().lower() for a in os.getenv("SWAY_ASSET", "btc").split(",") if a.strip()]


def fetch_recent(asset, n, workers=8):
    """Fetch the latest n resolved markets for an asset, with spot attached."""
    now = int(time.time())
    base = now - (now % 300)
    # skip the in-progress window; scan back, over-sampling for gaps
    slugs = [f"{asset}-updown-5m-{base - i * 300}" for i in range(2, n * 3 + 2)]
    sym = symbol_for(asset)
    collected = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_market, s): s for s in slugs}
        for fut in as_completed(futs):
            m = fut.result()
            if m is None:
                continue
            rec = fetch_spot(m["market_start"], symbol=sym)
            if rec is None:
                continue
            m["spot"] = rec
            collected.append(m)
            if len(collected) >= n:
                break
        for fut in futs:
            fut.cancel()
    return collected


def retrain():
    t0 = time.time()
    print(f"[RetrainCombined] assets={ASSETS} markets/asset={RETRAIN_MARKETS}", flush=True)

    markets = []
    for a in ASSETS:
        got = fetch_recent(a, RETRAIN_MARKETS)
        print(f"[RetrainCombined]   {a}: {len(got)} markets", flush=True)
        markets += got

    if len(markets) < 50:
        print(f"[RetrainCombined] Too few markets ({len(markets)}) — aborting.", flush=True)
        return False

    X, y, _ = build_training_table(markets, extract_combined_features)
    if len(X) < 100:
        print(f"[RetrainCombined] Too few samples ({len(X)}) — aborting.", flush=True)
        return False
    feature_names = list(X.columns)

    from sklearn.ensemble import GradientBoostingClassifier
    model = GradientBoostingClassifier(
        n_estimators=350, max_depth=3, learning_rate=0.03, subsample=0.8,
        random_state=42)
    model.fit(X.fillna(0.0).values, y)

    artifact = {
        "model": model,
        "feature_names": feature_names,
        "strategy": "Universal Combined-GBM (spot + prediction-market fusion)",
        "metadata": {
            "assets": ASSETS,
            "trained_on_markets": len(markets),
            "n_features": len(feature_names),
            "n_samples": int(len(X)),
            "training_date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        },
    }

    tmp = OUTPUT + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(artifact, f)
    os.replace(tmp, OUTPUT)

    print(f"[RetrainCombined] Done in {time.time()-t0:.0f}s | {len(markets)} markets | "
          f"{len(X)} samples -> {OUTPUT}", flush=True)
    return True


if __name__ == "__main__":
    sys.exit(0 if retrain() else 1)
