#!/usr/bin/env python3
"""
Underlying BTC spot price cache (Binance BTCUSDT 1-second klines).

The Polymarket BTC 5-minute up/down markets resolve on whether BTC closes the
window above/below its open. The prediction-market trade data only sees the
crowd's *opinion* of that; the spot price is the actual driver. This module
caches the 1s spot series for each market window so strategies can use it
(with no look-ahead: only spot ticks up to the prediction time are read).

Cached per market window (keyed by market_start):
  rel    : np.float64 seconds since window open (0..300)
  close  : np.float64 BTC close price at each second
  open   : float, price at window open
"""

import os
import gzip
import pickle
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
SPOT_DIR = os.path.join(_DIR, "cache", "spot")
os.makedirs(SPOT_DIR, exist_ok=True)

HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]
import threading
_local = threading.local()

# Polymarket asset prefix -> Binance spot symbol
ASSET_SYMBOL = {
    "btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT",
    "xrp": "XRPUSDT", "doge": "DOGEUSDT", "bnb": "BNBUSDT",
}


def symbol_for(asset):
    return ASSET_SYMBOL.get(str(asset).lower(), "BTCUSDT")


def _sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def _path(market_start, symbol="BTCUSDT"):
    # BTC keeps the legacy bare filename for backward compatibility; others are prefixed.
    if symbol == "BTCUSDT":
        return os.path.join(SPOT_DIR, f"{market_start}.pkl.gz")
    return os.path.join(SPOT_DIR, f"{symbol}_{market_start}.pkl.gz")


def fetch_spot(market_start, force=False, tries=4, symbol="BTCUSDT"):
    p = _path(market_start, symbol)
    if os.path.exists(p) and not force:
        try:
            with gzip.open(p, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass
    params = {"symbol": symbol, "interval": "1s",
              "startTime": market_start * 1000, "endTime": (market_start + 300) * 1000}
    for attempt in range(tries):
        host = HOSTS[attempt % len(HOSTS)]
        try:
            r = _sess().get(host + "/api/v3/klines", params=params, timeout=12)
            if r.status_code == 200:
                k = r.json()
                if len(k) < 30:
                    return None
                t = np.array([row[0] / 1000.0 - market_start for row in k], dtype=float)
                close = np.array([float(row[4]) for row in k], dtype=float)
                rec = {"market_start": market_start, "rel": t, "close": close,
                       "open": float(k[0][1])}
                with gzip.open(p, "wb") as f:
                    pickle.dump(rec, f)
                return rec
            if r.status_code in (429, 418, 500, 502, 503):
                time.sleep(0.6 * (attempt + 1))
                continue
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return None


def build_spot_cache(markets, max_workers=8, label="spot"):
    """Fetch + cache spot series for every market dict; returns dict[market_start]=rec."""
    out = {}
    todo = [(m["market_start"], symbol_for(m.get("asset", "btc"))) for m in markets]
    print(f"[{label}] fetching spot for {len(todo)} windows ({max_workers} workers)...")
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fetch_spot, ms, False, 4, sym): ms for ms, sym in todo}
        for fut in as_completed(futs):
            ms = futs[fut]
            rec = fut.result()
            if rec is not None:
                out[ms] = rec
            done += 1
            if done % 100 == 0:
                print(f"[{label}]   {done}/{len(todo)} ({time.time()-t0:.0f}s)")
    print(f"[{label}] got {len(out)}/{len(todo)} spot series in {time.time()-t0:.0f}s")
    return out


def load_spot_for(markets):
    """Load cached spot recs for the given markets (must already be fetched)."""
    out = {}
    for m in markets:
        ms = m["market_start"]
        p = _path(ms, symbol_for(m.get("asset", "btc")))
        if os.path.exists(p):
            try:
                with gzip.open(p, "rb") as f:
                    out[ms] = pickle.load(f)
            except Exception:
                pass
    return out


if __name__ == "__main__":
    import argparse
    from datacache import load_dataset
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", nargs="+", default=["train_set", "test_set", "val_set"])
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    for name in args.sets:
        ds = load_dataset(name)
        build_spot_cache(ds, max_workers=args.workers, label=name)
