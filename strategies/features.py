#!/usr/bin/env python3
"""
Rich, no-look-ahead feature extraction for BTC 5-minute up/down markets.

Given a cached market dict (see datacache.py) and an `elapsed` time (seconds
since market_start), compute a flat feature dict using ONLY trades with
rel_time <= elapsed.

Two key design points vs the existing "sway" model:
  1. We keep the ABSOLUTE price level (last_price, vwap, dist_from_half).
     The market's UP-token price IS the crowd probability — the single most
     predictive feature, which the sway model discards.
  2. We add order-flow (signed volume, buy fraction) and multi-horizon
     momentum / volatility microstructure features.

The original 29 sway features are also reproduced (extract_sway_features) so the
baseline sway model can be scored on the exact same cached markets.
"""

import numpy as np

WINDOW_SIZES = [10, 15, 20, 30, 60]
MIN_POINTS = 3
ROLLING_STEPS = 5
ROLLING_STEP_SIZE = 5

# ----------------------------------------------------------------------
# Sway primitives (identical math to sway_model.py / backtest.py)
# ----------------------------------------------------------------------

def fit_channel(x, y):
    if len(x) < 2:
        return 0, 0, 0
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)) or np.ptp(x) == 0:
        return 0, 0, 0
    try:
        m, c = np.polyfit(x, y, 1)
    except (np.linalg.LinAlgError, ValueError):
        return 0, 0, 0
    resid = y - (m * x + c)
    return m, c + resid.min(), c + resid.max()


def sway_at(times, prices, market_start, elapsed, window):
    rel = times - market_start
    mask = rel <= elapsed
    rt, pr = rel[mask], prices[mask]
    wstart = elapsed - window
    wmask = (rt >= wstart) & (rt <= elapsed)
    x, y = rt[wmask] - wstart, pr[wmask]
    if len(x) < MIN_POINTS:
        return np.nan
    m, a, b = fit_channel(x, y)
    width = b - a
    return m / width if width > 1e-9 else np.nan


def extract_sway_features(market, elapsed):
    """Reproduce the 29 v2 sway features for the baseline model."""
    times, prices = market["times"], market["prices"]
    market_start = market["market_start"]
    rel = times - market_start
    if (rel <= elapsed).sum() < MIN_POINTS:
        return None

    step_times = [elapsed - i * ROLLING_STEP_SIZE for i in range(ROLLING_STEPS)]
    f = {}
    for w in WINDOW_SIZES:
        vals = []
        for st in step_times:
            vals.append(np.nan if st < w else sway_at(times, prices, market_start, st, w))
        valid = [v for v in vals if not np.isnan(v)]
        dc = len(valid)
        last = vals[0] if not np.isnan(vals[0]) else 0.0
        mean = float(np.mean(valid)) if dc > 0 else 0.0
        std = float(np.std(valid)) if dc > 1 else 0.0
        trend = float(np.mean(np.diff(list(reversed(valid))))) if dc > 1 else 0.0
        f[f"sway_{w}s_last"] = last
        f[f"sway_{w}s_mean"] = mean
        f[f"sway_{w}s_std"] = std
        f[f"sway_{w}s_trend"] = trend
        f[f"sway_{w}s_data_count"] = float(dc)
    last_vals = [f[f"sway_{w}s_last"] for w in WINDOW_SIZES]
    nz = [v for v in last_vals if v != 0.0]
    f["sway_agreement"] = (2.0 * sum(1 for v in nz if v > 0) / len(nz) - 1.0) if nz else 0.0
    f["sway_magnitude"] = float(np.mean([abs(v) for v in last_vals]))
    f["short_long_div"] = f["sway_10s_last"] - f["sway_60s_last"]
    f["time_remaining"] = float(300 - elapsed)
    return f


SWAY_FEATURE_NAMES = [
    'sway_10s_last', 'sway_10s_mean', 'sway_10s_std', 'sway_10s_trend', 'sway_10s_data_count',
    'sway_15s_last', 'sway_15s_mean', 'sway_15s_std', 'sway_15s_trend', 'sway_15s_data_count',
    'sway_20s_last', 'sway_20s_mean', 'sway_20s_std', 'sway_20s_trend', 'sway_20s_data_count',
    'sway_30s_last', 'sway_30s_mean', 'sway_30s_std', 'sway_30s_trend', 'sway_30s_data_count',
    'sway_60s_last', 'sway_60s_mean', 'sway_60s_std', 'sway_60s_trend', 'sway_60s_data_count',
    'sway_agreement', 'sway_magnitude', 'short_long_div', 'time_remaining',
]


# ----------------------------------------------------------------------
# Rich microstructure features
# ----------------------------------------------------------------------

def _slope(x, y):
    if len(x) < 2 or np.ptp(x) == 0:
        return 0.0
    try:
        m, _ = np.polyfit(x, y, 1)
        return float(m)
    except Exception:
        return 0.0


def extract_features(market, elapsed):
    """
    Comprehensive flat feature dict using only data up to `elapsed`.
    Returns None if there are too few trades.
    """
    times = market["times"]
    prices = market["prices"]
    sizes = market["sizes"]
    sides = market["sides"]
    ms = market["market_start"]

    rel = times - ms
    mask = rel <= elapsed
    rt = rel[mask]
    pr = prices[mask]
    sz = sizes[mask]
    sd = sides[mask].astype(float)
    if len(rt) < MIN_POINTS:
        return None

    f = {}
    f["time_remaining"] = float(300 - elapsed)
    f["elapsed"] = float(elapsed)

    # --- absolute price level (the crowd probability) ---
    last_price = float(pr[-1])
    f["last_price"] = last_price
    f["dist_from_half"] = last_price - 0.5
    f["logit_price"] = float(np.log(np.clip(last_price, 1e-3, 1 - 1e-3) /
                                    np.clip(1 - last_price, 1e-3, 1 - 1e-3)))

    # global stats over all data so far
    f["price_mean_all"] = float(np.mean(pr))
    f["price_first"] = float(pr[0])
    f["price_drift_all"] = last_price - float(pr[0])
    f["n_trades_all"] = float(len(rt))

    # volume-weighted average price over all data
    tot_sz = float(np.sum(sz))
    f["vwap_all"] = float(np.sum(pr * sz) / tot_sz) if tot_sz > 0 else last_price
    f["total_volume"] = tot_sz

    # --- windowed features ---
    for w in WINDOW_SIZES:
        wmask = rt >= (elapsed - w)
        wp = pr[wmask]
        wt = rt[wmask]
        ws = sz[wmask]
        wd = sd[wmask]
        n = len(wp)
        pref = f"w{w}"
        if n >= 2:
            f[f"{pref}_ret"] = float(wp[-1] - wp[0])          # price change over window
            f[f"{pref}_slope"] = _slope(wt, wp)               # per-second drift
            f[f"{pref}_std"] = float(np.std(wp))              # volatility
            f[f"{pref}_range"] = float(np.max(wp) - np.min(wp))
            f[f"{pref}_mean"] = float(np.mean(wp))
        else:
            f[f"{pref}_ret"] = 0.0
            f[f"{pref}_slope"] = 0.0
            f[f"{pref}_std"] = 0.0
            f[f"{pref}_range"] = 0.0
            f[f"{pref}_mean"] = last_price
        f[f"{pref}_ntrades"] = float(n)
        # order flow: signed volume + buy fraction
        wv = float(np.sum(ws))
        f[f"{pref}_vol"] = wv
        f[f"{pref}_signed_vol"] = float(np.sum(ws * wd))
        f[f"{pref}_imbalance"] = float(np.sum(ws * wd) / wv) if wv > 0 else 0.0
        f[f"{pref}_buyfrac"] = float(np.mean((wd > 0).astype(float))) if n > 0 else 0.5

    # --- momentum / acceleration across horizons ---
    def price_at_ago(sec):
        m2 = rt <= (elapsed - sec)
        return float(pr[m2][-1]) if m2.any() else float(pr[0])

    p10, p30, p60 = price_at_ago(10), price_at_ago(30), price_at_ago(60)
    f["mom_10"] = last_price - p10
    f["mom_30"] = last_price - p30
    f["mom_60"] = last_price - p60
    f["accel"] = (last_price - p10) - (p10 - p30)   # change in momentum

    # short vs long divergence of slopes
    f["slope_div"] = f["w10_slope"] - f["w60_slope"]
    # interaction: price level scaled by time remaining
    f["price_x_timerem"] = f["dist_from_half"] * (f["time_remaining"] / 300.0)

    return f


# Feature groups for different strategies
def all_feature_names(sample_feat):
    return sorted(sample_feat.keys())
