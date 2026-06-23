#!/usr/bin/env python3
"""
Live inference for the sway v2 model.

Reads JSON from stdin:
  {
    "times":        [unix_ts, ...],  // absolute unix timestamps
    "prices":       [float, ...],    // UP-outcome mid-prices (0.0 – 1.0)
    "market_start": int,             // unix timestamp of market window start
    "elapsed":      int,             // seconds elapsed at prediction time
    "remaining":    int              // seconds remaining (= 300 - elapsed)
  }

Writes JSON to stdout:
  {
    "outcome":           "UP" | "DOWN",
    "confidence":        float,   // 0.0 – 1.0
    "raw_prediction":    float,   // raw model output (>0.5 → UP)
    "features_computed": bool
  }
"""

import sys
import json
import os
import warnings

warnings.filterwarnings('ignore')

import numpy as np

# ── Constants (must stay in sync with sway_model.py / backtest.py) ──────────

MIN_POINTS_PER_WINDOW = 3
ROLLING_STEPS = 5
ROLLING_STEP_SIZE = 5
WINDOW_SIZES = [10, 15, 20, 30, 60]

V2_FEATURE_NAMES = [
    'sway_10s_last', 'sway_10s_mean', 'sway_10s_std', 'sway_10s_trend', 'sway_10s_data_count',
    'sway_15s_last', 'sway_15s_mean', 'sway_15s_std', 'sway_15s_trend', 'sway_15s_data_count',
    'sway_20s_last', 'sway_20s_mean', 'sway_20s_std', 'sway_20s_trend', 'sway_20s_data_count',
    'sway_30s_last', 'sway_30s_mean', 'sway_30s_std', 'sway_30s_trend', 'sway_30s_data_count',
    'sway_60s_last', 'sway_60s_mean', 'sway_60s_std', 'sway_60s_trend', 'sway_60s_data_count',
    'sway_agreement', 'sway_magnitude', 'short_long_div', 'time_remaining',
]

# ── Sway calculation (identical to backtest.py) ──────────────────────────────

def fit_channel(x, y):
    if len(x) < 2:
        return 0, 0, 0
    m, c = np.polyfit(x, y, 1)
    resid = y - (m * x + c)
    return m, c + resid.min(), c + resid.max()


def calculate_sway_at_time(times, prices, market_start, prediction_seconds, window_size):
    rel_times = times - market_start
    mask = rel_times <= prediction_seconds
    rel_times_c = rel_times[mask]
    prices_c = prices[mask]
    if len(rel_times_c) < MIN_POINTS_PER_WINDOW:
        return np.nan
    window_start = prediction_seconds - window_size
    wmask = (rel_times_c >= window_start) & (rel_times_c <= prediction_seconds)
    x = rel_times_c[wmask] - window_start
    y = prices_c[wmask]
    if len(x) < MIN_POINTS_PER_WINDOW:
        return np.nan
    m, a, b = fit_channel(x, y)
    width = b - a
    if width > 1e-9:
        return m / width
    return np.nan


def extract_features_v2(times, prices, market_start, elapsed):
    """Compute 29 v2 features — identical logic to backtest.py extract_features_v2."""
    rel_times = times - market_start
    if (rel_times <= elapsed).sum() < MIN_POINTS_PER_WINDOW:
        return None

    step_times = [elapsed - i * ROLLING_STEP_SIZE for i in range(ROLLING_STEPS)]
    features = {}

    for w in WINDOW_SIZES:
        sway_vals = []
        for step_t in step_times:
            if step_t < w:
                sway_vals.append(np.nan)
                continue
            sway_vals.append(calculate_sway_at_time(times, prices, market_start, step_t, w))

        valid = [v for v in sway_vals if not np.isnan(v)]
        data_count = len(valid)
        last = sway_vals[0] if not np.isnan(sway_vals[0]) else 0.0
        mean = float(np.mean(valid)) if data_count > 0 else 0.0
        std = float(np.std(valid)) if data_count > 1 else 0.0
        if data_count > 1:
            chrono = list(reversed(valid))
            trend = float(np.mean(np.diff(chrono)))
        else:
            trend = 0.0

        features[f'sway_{w}s_last'] = last
        features[f'sway_{w}s_mean'] = mean
        features[f'sway_{w}s_std'] = std
        features[f'sway_{w}s_trend'] = trend
        features[f'sway_{w}s_data_count'] = float(data_count)

    last_vals = [features[f'sway_{w}s_last'] for w in WINDOW_SIZES]
    nonzero = [v for v in last_vals if v != 0.0]
    if nonzero:
        pos_frac = sum(1 for v in nonzero if v > 0) / len(nonzero)
        features['sway_agreement'] = 2.0 * pos_frac - 1.0
    else:
        features['sway_agreement'] = 0.0

    features['sway_magnitude'] = float(np.mean([abs(v) for v in last_vals]))
    features['short_long_div'] = features['sway_10s_last'] - features['sway_60s_last']
    features['time_remaining'] = float(300 - elapsed)

    return features


# ── Model loading ────────────────────────────────────────────────────────────

def load_model():
    import joblib
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Prefer the live model (kept fresh by retrain.py); fall back to the best
    # static model (v4) when a live model doesn't exist yet.
    for name in ('sway_model_live.pkl', 'sway_model_v4_production.pkl', 'sway_model_v2_production.pkl'):
        path = os.path.join(script_dir, name)
        if os.path.exists(path):
            return joblib.load(path)
    raise FileNotFoundError(f"No sway model found in {script_dir}")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    data = json.load(sys.stdin)

    times = np.array(data['times'], dtype=float)
    prices = np.array(data['prices'], dtype=float)
    market_start = float(data['market_start'])
    elapsed = float(data['elapsed'])
    remaining = int(data['remaining'])

    features = extract_features_v2(times, prices, market_start, elapsed)
    if features is None:
        json.dump({
            'outcome': 'UNKNOWN',
            'confidence': 0.0,
            'raw_prediction': 0.5,
            'features_computed': False,
            'error': 'insufficient_data',
        }, sys.stdout)
        return

    model_data = load_model()
    slot = model_data['models'].get(remaining)
    if slot is None:
        json.dump({
            'outcome': 'UNKNOWN',
            'confidence': 0.0,
            'raw_prediction': 0.5,
            'features_computed': True,
            'error': f'no_model_slot_{remaining}',
        }, sys.stdout)
        return

    import pandas as pd
    X = pd.DataFrame([[features[n] for n in V2_FEATURE_NAMES]], columns=V2_FEATURE_NAMES)
    pred = float(slot['model'].predict(X)[0])
    pred = max(0.0, min(1.0, pred))

    outcome = 'UP' if pred > 0.5 else 'DOWN'
    confidence = abs(pred - 0.5) * 2.0

    sway_vals = {
        f'sway_{w}s': round(features[f'sway_{w}s_last'], 6)
        for w in WINDOW_SIZES
    }

    json.dump({
        'outcome': outcome,
        'confidence': round(confidence, 4),
        'raw_prediction': round(pred, 4),
        'features_computed': True,
        'sway_values': sway_vals,
        'sway_agreement': round(features['sway_agreement'], 4),
        'sway_magnitude': round(features['sway_magnitude'], 6),
        'short_long_div': round(features['short_long_div'], 6),
        'time_remaining': int(features['time_remaining']),
    }, sys.stdout)


if __name__ == '__main__':
    main()
