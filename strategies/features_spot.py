#!/usr/bin/env python3
"""
Spot-aware feature extraction.

Reads the underlying BTC spot series attached to a market dict as market['spot']
(see spotcache.py) and computes features at `elapsed` seconds with no look-ahead
(only spot ticks with rel <= elapsed are used).

The headline idea is a first-passage / digital-option probability: given the
current lead over the window open and the realised per-second volatility, what is
the probability the window still closes UP after the remaining seconds? If the
crowd misprices this barrier probability, there is a tradeable edge.
"""

import numpy as np
from math import erf, sqrt

from features import extract_features


def _phi(z):
    """Standard normal CDF."""
    return 0.5 * (1.0 + erf(z / sqrt(2.0)))


def _spot_state(rec, elapsed):
    """Return (open, cur, rel_used, close_used) using only ticks up to elapsed."""
    rel, close = rec["rel"], rec["close"]
    mask = rel <= elapsed
    if mask.sum() < 5:
        return None
    return rec["open"], close[mask][-1], rel[mask], close[mask]


def extract_spot_features(market, elapsed):
    rec = market.get("spot")
    if rec is None:
        return None
    st = _spot_state(rec, elapsed)
    if st is None:
        return None
    open_px, cur, rel, close = st
    remaining = max(1.0, 300.0 - elapsed)

    f = {}
    lead = cur - open_px
    f["spot_lead"] = lead
    f["spot_lead_bps"] = (lead / open_px) * 1e4 if open_px else 0.0
    f["spot_cur_minus_open"] = lead
    f["time_remaining"] = float(remaining)

    # per-second log/price returns so far
    if len(close) >= 3:
        diffs = np.diff(close)
        sigma_s = float(np.std(diffs)) if len(diffs) > 1 else 0.0
        # recent volatility (last 60s)
        rmask = rel >= (elapsed - 60)
        rdiffs = np.diff(close[rmask]) if rmask.sum() > 2 else diffs
        sigma_recent = float(np.std(rdiffs)) if len(rdiffs) > 1 else sigma_s
    else:
        sigma_s = sigma_recent = 0.0
    f["spot_sigma_s"] = sigma_s
    f["spot_sigma_recent"] = sigma_recent
    f["spot_realized_vol_bps"] = (sigma_s / open_px) * 1e4 if open_px else 0.0

    # ---- first-passage / digital barrier probability ----
    # P(close > open) ~= Phi( lead / (sigma * sqrt(remaining)) ), random-walk approx
    denom = (sigma_recent if sigma_recent > 1e-9 else sigma_s) * sqrt(remaining)
    z = lead / denom if denom > 1e-9 else (50.0 if lead > 0 else -50.0)
    f["spot_lead_z"] = float(np.clip(z, -50, 50))
    f["spot_barrier_prob"] = float(np.clip(_phi(z), 0.0, 1.0))

    # ---- spot momentum over horizons ----
    def px_ago(sec):
        m2 = rel <= (elapsed - sec)
        return float(close[m2][-1]) if m2.any() else float(close[0])
    f["spot_mom_10"] = cur - px_ago(10)
    f["spot_mom_30"] = cur - px_ago(30)
    f["spot_mom_60"] = cur - px_ago(60)
    # acceleration
    f["spot_accel"] = (cur - px_ago(10)) - (px_ago(10) - px_ago(30))
    # range / position within window range
    hi, lo = float(close.max()), float(close.min())
    rng = hi - lo
    f["spot_range_bps"] = (rng / open_px) * 1e4 if open_px else 0.0
    f["spot_pos_in_range"] = (cur - lo) / rng if rng > 1e-9 else 0.5
    # fraction of recent seconds spent above open
    f["spot_frac_above_open"] = float(np.mean(close[rel >= (elapsed - 60)] > open_px)) \
        if (rel >= (elapsed - 60)).any() else float(cur > open_px)
    return f


def extract_combined_features(market, elapsed):
    """Rich prediction-market features + spot features (prefixed). None if spot missing."""
    sf = extract_spot_features(market, elapsed)
    if sf is None:
        return None
    rf = extract_features(market, elapsed)
    if rf is None:
        # still allow spot-only when market trade data is thin
        return dict(sf)
    out = dict(rf)
    out.update(sf)
    return out
