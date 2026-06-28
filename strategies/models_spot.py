#!/usr/bin/env python3
"""
Spot-driven strategies: use the underlying BTC price (Binance 1s klines) that the
prediction-market models never see.

  SpotBarrier      - analytic first-passage probability, no training
  SpotBarrierCal   - barrier prob recalibrated with a 1-feature logistic
  SpotML-Logistic  - logistic on spot features
  SpotML-GBM       - gradient boosting on spot features
  Combined-GBM     - gradient boosting on spot + prediction-market features
  Combined-Logistic- logistic on spot + prediction-market features
  SpotMktEdge      - bets the barrier prob vs the crowd price (trading-focused)

Market dicts must be enriched with m['spot'] (see attach_spot) before fit/eval.
"""

import numpy as np
import pandas as pd

from models import build_training_table
from features_spot import (
    extract_spot_features, extract_combined_features,
)
from spotcache import load_spot_for


def attach_spot(markets):
    """Attach cached spot recs to market dicts in place; drop those without spot."""
    spot = load_spot_for(markets)
    out = []
    for m in markets:
        rec = spot.get(m["market_start"])
        if rec is not None:
            m["spot"] = rec
            out.append(m)
    return out


# ----------------------------------------------------------------------
# Analytic (no-training) barrier strategies
# ----------------------------------------------------------------------

class SpotBarrier:
    """P(UP) = first-passage probability from spot lead + realised vol."""
    name = "SpotBarrier"

    def fit(self, markets):
        return self

    def predict(self, market, elapsed, remaining):
        f = extract_spot_features(market, elapsed)
        if f is None:
            return None
        return float(np.clip(f["spot_barrier_prob"], 0.0, 1.0))


class SpotBarrierCal:
    """Barrier prob passed through a learned 1-feature logistic (fixes ref offset/scale)."""
    name = "SpotBarrierCal"

    def __init__(self):
        self.a = 1.0
        self.b = 0.0

    def fit(self, markets):
        from sklearn.linear_model import LogisticRegression
        X, y, _ = build_training_table(markets, extract_spot_features)
        z = X["spot_lead_z"].fillna(0.0).clip(-50, 50).values.reshape(-1, 1)
        lr = LogisticRegression(max_iter=1000)
        lr.fit(z, y)
        self.lr = lr
        return self

    def predict(self, market, elapsed, remaining):
        f = extract_spot_features(market, elapsed)
        if f is None:
            return None
        z = np.array([[np.clip(f["spot_lead_z"], -50, 50)]])
        return float(np.clip(self.lr.predict_proba(z)[0, 1], 0.0, 1.0))


# ----------------------------------------------------------------------
# Generic ML base with pluggable feature function
# ----------------------------------------------------------------------

class _SpotMLBase:
    name = "SpotML"
    feature_fn = staticmethod(extract_spot_features)

    def __init__(self):
        self.model = None
        self.feature_names = None

    def _make_model(self):
        raise NotImplementedError

    def fit(self, markets):
        X, y, _ = build_training_table(markets, self.feature_fn)
        self.feature_names = list(X.columns)
        self.model = self._make_model()
        self.model.fit(X.fillna(0.0).values, y)
        return self

    def predict(self, market, elapsed, remaining):
        if self.model is None:
            return None
        f = self.feature_fn(market, elapsed)
        if f is None:
            return None
        x = np.nan_to_num(np.array([[f.get(k, 0.0) for k in self.feature_names]], dtype=float))
        return float(np.clip(self.model.predict_proba(x)[0, 1], 0.0, 1.0))


class SpotLogistic(_SpotMLBase):
    name = "SpotML-Logistic"
    feature_fn = staticmethod(extract_spot_features)

    def _make_model(self):
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import LogisticRegression
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))


class SpotGBM(_SpotMLBase):
    name = "SpotML-GBM"
    feature_fn = staticmethod(extract_spot_features)

    def _make_model(self):
        from sklearn.ensemble import GradientBoostingClassifier
        return GradientBoostingClassifier(
            n_estimators=300, max_depth=3, learning_rate=0.03, subsample=0.8,
            random_state=42)


class CombinedLogistic(_SpotMLBase):
    name = "Combined-Logistic"
    feature_fn = staticmethod(extract_combined_features)

    def _make_model(self):
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import LogisticRegression
        return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=0.5))


class CombinedGBM(_SpotMLBase):
    name = "Combined-GBM"
    feature_fn = staticmethod(extract_combined_features)

    def _make_model(self):
        from sklearn.ensemble import GradientBoostingClassifier
        return GradientBoostingClassifier(
            n_estimators=350, max_depth=3, learning_rate=0.03, subsample=0.8,
            random_state=42)
