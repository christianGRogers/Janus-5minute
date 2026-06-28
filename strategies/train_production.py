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
    # Freshest markets first (test_set ~1 day old, train_set ~3 days old)
    markets = []
    for name in ("test_set", "train_set"):
        try:
            markets += attach_spot(load_dataset(name))
        except Exception as e:
            print(f"  skip {name}: {e}")
    print(f"Training Combined-Logistic on {len(markets)} markets (with spot)...")

    X, y, _ = build_training_table(markets, extract_combined_features)
    feature_names = list(X.columns)

    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))
    model.fit(X.fillna(0.0).values, y)

    artifact = {
        "model": model,
        "feature_names": feature_names,
        "strategy": "Combined-Logistic (spot + prediction-market fusion)",
        "metadata": {
            "trained_on_markets": len(markets),
            "n_features": len(feature_names),
            "training_date": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "note": "Recommended robust strategy from STRATEGY_REPORT.pdf. "
                    "Inference requires live Binance BTCUSDT 1s spot; see spot_predict.py.",
        },
    }
    with open(OUT, "wb") as f:
        pickle.dump(artifact, f)
    print(f"Saved {OUT}  ({len(feature_names)} features)")


if __name__ == "__main__":
    main()
