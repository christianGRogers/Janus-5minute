#!/usr/bin/env python3
"""
Train and save the recommended production model.

The research (see STRATEGY_REPORT.pdf) found that a regularised fusion of spot +
prediction-market features (Combined-Logistic) is the most robust profitable
strategy under realistic per-window retraining. This script trains it on the
freshest available markets and saves a self-contained artifact for inference by
spot_predict.py.

Output: strategies/combined_model_production.pkl
"""

import os
import time
import pickle

import numpy as np

from datacache import load_dataset
from models_spot import attach_spot
from models import build_training_table
from features_spot import extract_combined_features

_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(_DIR, "combined_model_production.pkl")


def main():
    # Universal model: pool all available assets (asset-agnostic features).
    candidates = ["test_set", "train_set", "eth_test", "eth_train",
                  "sol_test", "sol_train"]
    markets, used = [], []
    for name in candidates:
        try:
            markets += attach_spot(load_dataset(name))
            used.append(name)
        except Exception:
            pass
    assets = sorted({m.get("asset", "btc") for m in markets})
    print(f"Training universal Combined-GBM on {len(markets)} markets "
          f"({'+'.join(assets)}) from {len(used)} datasets...")

    X, y, _ = build_training_table(markets, extract_combined_features)
    feature_names = list(X.columns)

    from sklearn.ensemble import GradientBoostingClassifier
    model = GradientBoostingClassifier(
        n_estimators=350, max_depth=3, learning_rate=0.03, subsample=0.8,
        random_state=42)
    model.fit(X.fillna(0.0).values, y)

    artifact = {
        "model": model,
        "feature_names": feature_names,
        "strategy": "Universal Combined-GBM (spot + prediction-market fusion, "
                    "pooled across assets)",
        "metadata": {
            "trained_on_markets": len(markets),
            "assets": assets,
            "n_features": len(feature_names),
            "training_date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "note": "Recommended robust strategy from STRATEGY_REPORT.pdf. Universal "
                    "across crypto 5-min markets. Inference fetches live Binance 1s spot "
                    "for the asset's symbol; see spot_predict.py (pass \"asset\").",
        },
    }
    with open(OUT, "wb") as f:
        pickle.dump(artifact, f)
    print(f"Saved {OUT}  ({len(feature_names)} features)")


if __name__ == "__main__":
    main()
