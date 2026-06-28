#!/usr/bin/env python3
"""
Candidate trading strategies for BTC 5-minute up/down prediction.

Every strategy implements:
    name           -> str
    fit(markets)   -> train on a list of cached market dicts (no-op for some)
    predict(market, elapsed, remaining) -> float in [0,1] (P(UP)) or None

Strategies are evaluated on identical held-out markets by backtest_harness.py.
"""

import numpy as np
import pandas as pd

from features import (
    extract_features, extract_sway_features, SWAY_FEATURE_NAMES,
)

REMAINING_TIMES = [60, 30, 20, 15, 10]
LOOKUP_TOL = 2.0


# ----------------------------------------------------------------------
# Training-sample builder
# ----------------------------------------------------------------------

def build_training_table(markets, feature_fn):
    """
    Build (DataFrame X, y, remaining) from markets using feature_fn(market, elapsed).
    One row per (market, remaining) where data is available.
    """
    rows, ys, rems = [], [], []
    for m in markets:
        rel_max = (m["times"] - m["market_start"]).max() if len(m["times"]) else -1
        for remaining in REMAINING_TIMES:
            elapsed = 300 - remaining
            if rel_max < elapsed - LOOKUP_TOL:
                continue
            feat = feature_fn(m, elapsed)
            if feat is None:
                continue
            rows.append(feat)
            ys.append(m["actual_bin"])
            rems.append(remaining)
    X = pd.DataFrame(rows)
    return X, np.array(ys), np.array(rems)


# ----------------------------------------------------------------------
# Baseline strategies (no ML)
# ----------------------------------------------------------------------

class MarketPriceStrategy:
    """Trust the crowd: predicted P(UP) = current UP-token price."""
    name = "MarketPrice"

    def fit(self, markets):
        return self

    def predict(self, market, elapsed, remaining):
        feat = extract_features(market, elapsed)
        if feat is None:
            return None
        return float(np.clip(feat["last_price"], 0.0, 1.0))


class MomentumStrategy:
    """Market price nudged by recent order-flow / momentum."""
    name = "Momentum"

    def __init__(self, k=0.5):
        self.k = k

    def fit(self, markets):
        return self

    def predict(self, market, elapsed, remaining):
        feat = extract_features(market, elapsed)
        if feat is None:
            return None
        p = feat["last_price"]
        nudge = self.k * (feat["mom_10"] + 0.5 * feat["w30_imbalance"] * 0.1)
        return float(np.clip(p + nudge, 0.0, 1.0))


# ----------------------------------------------------------------------
# Sway baseline (faithful reproduction of the repo model) -> the benchmark
# ----------------------------------------------------------------------

class SwayBaseline:
    """
    Per-remaining-slot GradientBoostingRegressor on the original 29 sway
    features, predicting resolution price. This is the existing 'sway model'.
    """
    name = "Sway (baseline)"

    def __init__(self):
        self.models = {}

    def fit(self, markets):
        from sklearn.ensemble import GradientBoostingRegressor
        X, y, rem = build_training_table(markets, extract_sway_features)
        X = X[SWAY_FEATURE_NAMES].fillna(0.0)
        for r in REMAINING_TIMES:
            mask = rem == r
            if mask.sum() < 20:
                continue
            mdl = GradientBoostingRegressor(
                n_estimators=200, max_depth=4, learning_rate=0.05,
                subsample=0.8, random_state=42)
            mdl.fit(X[mask], y[mask])
            self.models[r] = mdl
        return self

    def predict(self, market, elapsed, remaining):
        mdl = self.models.get(remaining)
        if mdl is None:
            return None
        feat = extract_sway_features(market, elapsed)
        if feat is None:
            return None
        X = pd.DataFrame([{k: feat.get(k, 0.0) for k in SWAY_FEATURE_NAMES}])[SWAY_FEATURE_NAMES]
        return float(np.clip(mdl.predict(X)[0], 0.0, 1.0))


# ----------------------------------------------------------------------
# Rich-feature ML strategies (pooled across slots, time_remaining is a feature)
# ----------------------------------------------------------------------

class _RichMLBase:
    """Shared plumbing for rich-feature models trained on actual_bin."""
    name = "RichML"

    def __init__(self):
        self.model = None
        self.feature_names = None
        self.is_classifier = True

    def _make_model(self):
        raise NotImplementedError

    def fit(self, markets):
        X, y, rem = build_training_table(markets, extract_features)
        self.feature_names = list(X.columns)
        Xv = X.fillna(0.0).values
        self.model = self._make_model()
        self.model.fit(Xv, y)
        return self

    def predict(self, market, elapsed, remaining):
        if self.model is None:
            return None
        feat = extract_features(market, elapsed)
        if feat is None:
            return None
        x = np.array([[feat.get(k, 0.0) for k in self.feature_names]], dtype=float)
        x = np.nan_to_num(x)
        if self.is_classifier:
            p = self.model.predict_proba(x)[0, 1]
        else:
            p = self.model.predict(x)[0]
        return float(np.clip(p, 0.0, 1.0))


class LogisticMicro(_RichMLBase):
    name = "LogisticMicro"

    def _make_model(self):
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import LogisticRegression
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, C=1.0),
        )


class GBMRich(_RichMLBase):
    name = "GBM-Rich"

    def _make_model(self):
        from sklearn.ensemble import GradientBoostingClassifier
        return GradientBoostingClassifier(
            n_estimators=300, max_depth=3, learning_rate=0.03, subsample=0.8,
            random_state=42)


class RandomForestRich(_RichMLBase):
    name = "RF-Rich"

    def _make_model(self):
        from sklearn.ensemble import RandomForestClassifier
        return RandomForestClassifier(
            n_estimators=400, max_depth=8, min_samples_leaf=20,
            random_state=42, n_jobs=-1)


class XGBRich(_RichMLBase):
    name = "XGB-Rich"

    def _make_model(self):
        from xgboost import XGBClassifier
        return XGBClassifier(
            n_estimators=400, max_depth=4, learning_rate=0.03, subsample=0.8,
            colsample_bytree=0.8, eval_metric="logloss",
            reg_lambda=1.0, random_state=42, n_jobs=-1)


class LGBMRich(_RichMLBase):
    name = "LGBM-Rich"

    def _make_model(self):
        from lightgbm import LGBMClassifier
        return LGBMClassifier(
            n_estimators=500, max_depth=5, num_leaves=31, learning_rate=0.03,
            subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0,
            min_child_samples=30, random_state=42, n_jobs=-1, verbose=-1)


# ----------------------------------------------------------------------
# Ensemble / blend
# ----------------------------------------------------------------------

class TimeSlotLogistic:
    """Separate logistic regression per remaining-time slot (vs pooled LogisticMicro)."""
    name = "Logistic-PerSlot"

    def __init__(self):
        self.models = {}
        self.feature_names = None

    def fit(self, markets):
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import LogisticRegression
        X, y, rem = build_training_table(markets, extract_features)
        self.feature_names = list(X.columns)
        Xv = X.fillna(0.0).values
        for r in REMAINING_TIMES:
            mask = rem == r
            if mask.sum() < 30:
                continue
            mdl = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
            mdl.fit(Xv[mask], y[mask])
            self.models[r] = mdl
        return self

    def predict(self, market, elapsed, remaining):
        mdl = self.models.get(remaining)
        if mdl is None:
            return None
        feat = extract_features(market, elapsed)
        if feat is None:
            return None
        x = np.nan_to_num(np.array([[feat.get(k, 0.0) for k in self.feature_names]], dtype=float))
        return float(np.clip(mdl.predict_proba(x)[0, 1], 0.0, 1.0))


class CalibratedLogistic(_RichMLBase):
    """Logistic regression with isotonic calibration."""
    name = "Logistic-Calib"

    def _make_model(self):
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import LogisticRegression
        from sklearn.calibration import CalibratedClassifierCV
        base = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0))
        return CalibratedClassifierCV(base, method="isotonic", cv=3)


class _EdgeBase:
    """
    Predict the crowd's *error*: target = actual_bin - market_price.
    Final P(UP) = clip(market_price + predicted_residual). Directly targets the
    mispricings a trading bot must find, instead of re-predicting the outcome.
    """
    name = "Edge"

    def __init__(self):
        self.model = None
        self.feature_names = None

    def _make_model(self):
        raise NotImplementedError

    def fit(self, markets):
        X, y, rem = build_training_table(markets, extract_features)
        self.feature_names = list(X.columns)
        price = X["last_price"].values
        resid = y - price                     # signed crowd error
        Xv = X.fillna(0.0).values
        self.model = self._make_model()
        self.model.fit(Xv, resid)
        return self

    def predict(self, market, elapsed, remaining):
        if self.model is None:
            return None
        feat = extract_features(market, elapsed)
        if feat is None:
            return None
        x = np.nan_to_num(np.array([[feat.get(k, 0.0) for k in self.feature_names]], dtype=float))
        resid = float(self.model.predict(x)[0])
        return float(np.clip(feat["last_price"] + resid, 0.0, 1.0))


class EdgeGBM(_EdgeBase):
    name = "Edge-GBM"

    def _make_model(self):
        from sklearn.ensemble import GradientBoostingRegressor
        return GradientBoostingRegressor(
            n_estimators=300, max_depth=3, learning_rate=0.02, subsample=0.8,
            random_state=42)


class EdgeRidge(_EdgeBase):
    name = "Edge-Ridge"

    def _make_model(self):
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.linear_model import Ridge
        return make_pipeline(StandardScaler(), Ridge(alpha=5.0))


class CalibratedXGB(_RichMLBase):
    """XGBoost with isotonic probability calibration (better EV decisions)."""
    name = "XGB-Calibrated"

    def _make_model(self):
        from xgboost import XGBClassifier
        from sklearn.calibration import CalibratedClassifierCV
        base = XGBClassifier(
            n_estimators=400, max_depth=4, learning_rate=0.03, subsample=0.8,
            colsample_bytree=0.8, eval_metric="logloss", reg_lambda=1.0,
            random_state=42, n_jobs=-1)
        return CalibratedClassifierCV(base, method="isotonic", cv=3)


class BlendStrategy:
    """
    Weighted average of sub-strategies, optionally shrunk toward market price.
    `shrink` in [0,1]: final = (1-shrink)*blend + shrink*market_price.
    """
    name = "Blend"

    def __init__(self, members, weights=None, shrink=0.0, name=None):
        self.members = members
        self.weights = weights or [1.0] * len(members)
        self.shrink = shrink
        if name:
            self.name = name

    def fit(self, markets):
        for m in self.members:
            m.fit(markets)
        return self

    def predict(self, market, elapsed, remaining):
        preds, ws = [], []
        for mem, w in zip(self.members, self.weights):
            p = mem.predict(market, elapsed, remaining)
            if p is not None:
                preds.append(p)
                ws.append(w)
        if not preds:
            return None
        blend = float(np.average(preds, weights=ws))
        if self.shrink > 0:
            feat = extract_features(market, elapsed)
            if feat is not None:
                mp = feat["last_price"]
                blend = (1 - self.shrink) * blend + self.shrink * mp
        return float(np.clip(blend, 0.0, 1.0))
