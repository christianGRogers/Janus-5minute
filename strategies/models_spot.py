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


class SpotBarrierDrift:
    """
    Barrier probability with a drift term: the pure random-walk model assumes
    zero drift, but recent spot momentum carries information. Estimate per-second
    drift from the last 30s and project it over the remaining time.
    P(UP) = Phi( (lead + drift*t_rem) / (sigma*sqrt(t_rem)) ).
    """
    name = "SpotBarrierDrift"

    def __init__(self, drift_k=0.5):
        self.drift_k = drift_k

    def fit(self, markets):
        return self

    def predict(self, market, elapsed, remaining):
        from math import sqrt
        f = extract_spot_features(market, elapsed)
        if f is None:
            return None
        lead = f["spot_cur_minus_open"]
        sigma = f["spot_sigma_recent"] or f["spot_sigma_s"]
        t_rem = max(1.0, f["time_remaining"])
        drift_per_s = self.drift_k * (f["spot_mom_30"] / 30.0)
        denom = sigma * sqrt(t_rem)
        if denom <= 1e-9:
            return 1.0 if (lead + drift_per_s * t_rem) > 0 else 0.0
        z = (lead + drift_per_s * t_rem) / denom
        return float(np.clip(_phi_np(z), 0.0, 1.0))


def _phi_np(z):
    from math import erf, sqrt as _sq
    return 0.5 * (1.0 + erf(float(np.clip(z, -50, 50)) / _sq(2.0)))


class SpotBarrierLate(SpotBarrier):
    """
    SpotBarrier restricted to the late slots (<= max_remaining s). With little
    time left, the spot lead is highly predictive yet the crowd still prices in
    residual caution -> the edge is largest and most consistent here. Returns
    None (no bet) for earlier slots.
    """
    name = "SpotBarrier-Late"

    def __init__(self, max_remaining=20):
        self.max_remaining = max_remaining

    def predict(self, market, elapsed, remaining):
        if remaining > self.max_remaining:
            return None
        return super().predict(market, elapsed, remaining)


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


class MarketTemperedBarrier:
    """
    SpotBarrier blended toward the crowd price. The pure barrier diverges from the
    market too aggressively and that divergence is what fails out-of-period; mixing
    in the crowd price tempers it. P(UP) = (1-w)*market_price + w*barrier_prob.
    `w` is set a priori (not tuned on the test windows).
    """
    def __init__(self, w=0.5):
        self.w = w
        self.name = f"TemperedBarrier(w={w})"

    def fit(self, markets):
        return self

    def predict(self, market, elapsed, remaining):
        from features import extract_features
        bf = extract_spot_features(market, elapsed)
        mf = extract_features(market, elapsed)
        if bf is None or mf is None:
            return None
        price = mf["last_price"]
        return float(np.clip((1 - self.w) * price + self.w * bf["spot_barrier_prob"],
                             0.0, 1.0))


class ConsensusStrategy:
    """
    Only bet when two orthogonal signals agree on direction vs the crowd price:
    a trained fusion model (Combined-GBM) and the independent analytic SpotBarrier.
    When they disagree, return the market price (=> no positive-EV divergence =>
    no bet). Higher precision by demanding consensus.
    """
    name = "Consensus"

    def __init__(self):
        self.fusion = CombinedGBM()
        self.barrier = SpotBarrier()

    def fit(self, markets):
        self.fusion.fit(markets)
        self.barrier.fit(markets)
        return self

    def predict(self, market, elapsed, remaining):
        from features import extract_features
        qc = self.fusion.predict(market, elapsed, remaining)
        qb = self.barrier.predict(market, elapsed, remaining)
        mf = extract_features(market, elapsed)
        if qc is None or qb is None or mf is None:
            return None
        p = float(np.clip(mf["last_price"], 0.01, 0.99))
        # both must point the same way relative to the crowd price
        if (qc - p) * (qb - p) > 0:
            return qc
        return p   # disagreement -> sit out


class SpotEdgeGBM:
    """
    Predict the crowd's error (actual - market_price) from spot + market features.
    Spot info is orthogonal to the crowd price, so this directly targets where the
    market is mispriced. Final P(UP) = clip(market_price + predicted_residual).
    """
    name = "SpotEdge-GBM"

    def __init__(self):
        self.model = None
        self.feature_names = None

    def fit(self, markets):
        from sklearn.ensemble import GradientBoostingRegressor
        X, y, _ = build_training_table(markets, extract_combined_features)
        self.feature_names = list(X.columns)
        price = X["last_price"].values if "last_price" in X.columns else np.full(len(X), 0.5)
        resid = y - price
        self.model = GradientBoostingRegressor(
            n_estimators=300, max_depth=3, learning_rate=0.02, subsample=0.8,
            random_state=42)
        self.model.fit(X.fillna(0.0).values, resid)
        return self

    def predict(self, market, elapsed, remaining):
        if self.model is None:
            return None
        f = extract_combined_features(market, elapsed)
        if f is None:
            return None
        x = np.nan_to_num(np.array([[f.get(k, 0.0) for k in self.feature_names]], dtype=float))
        resid = float(self.model.predict(x)[0])
        price = f.get("last_price", 0.5)
        return float(np.clip(price + resid, 0.0, 1.0))
