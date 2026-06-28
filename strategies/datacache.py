#!/usr/bin/env python3
"""
Data cache for BTC 5-minute up/down markets.

Fetches Polymarket trade data ONCE and caches it to disk so that strategy
backtesting / training can iterate offline at full speed.

Each cached market is stored as a compressed pickle holding:
  slug, market_start, actual_price, actual_bin,
  times   (np.float64, absolute unix ts of UP-token trades, sorted),
  prices  (np.float64, UP-token traded price 0..1),
  sizes   (np.float64, trade size),
  sides   (np.int8,    +1 = BUY up-token, -1 = SELL up-token)

A "dataset" is just an ordered list of such market dicts; we also pickle the
whole list to one file for fast bulk load.
"""

import os
import json
import time
import pickle
import gzip
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_DIR, "cache")
MKT_DIR = os.path.join(CACHE_DIR, "markets")
os.makedirs(MKT_DIR, exist_ok=True)

MIN_POINTS = 3

import threading
_local = threading.local()


def _sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def _get(url, params, timeout, tries=5):
    """GET with retry/backoff for rate limits & transient errors."""
    for attempt in range(tries):
        try:
            r = _sess().get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.5 * (attempt + 1) + 0.1 * attempt)
                continue
            return r
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return None


def _market_cache_path(slug):
    return os.path.join(MKT_DIR, f"{slug}.pkl.gz")


def fetch_event(slug):
    r = _get(f"{GAMMA_API}/events", {"slug": slug}, 10)
    if r is None or r.status_code != 200:
        return None
    try:
        d = r.json()
    except Exception:
        return None
    return d[0] if d else None


def _parse_market(event):
    m = event["markets"][0]
    cid = m["conditionId"]
    toks = m["clobTokenIds"]
    if isinstance(toks, str):
        toks = json.loads(toks)
    outs = m.get("outcomes", '["Up","Down"]')
    if isinstance(outs, str):
        outs = json.loads(outs)
    up_idx = 0
    for i, o in enumerate(outs):
        if str(o).strip().lower() in ("up", "yes"):
            up_idx = i
            break
    return {"condition_id": cid, "up_token": toks[up_idx]}


def _fetch_trades(condition_id, up_token):
    """Return times, prices, sizes, sides arrays for the UP token only."""
    all_trades = []
    page = 0
    page_size = 1000
    while True:
        r = _get(f"{DATA_API}/trades",
                 {"market": condition_id, "limit": page_size, "offset": page * page_size}, 15)
        if r is None or r.status_code != 200:
            break
        try:
            chunk = r.json()
        except Exception:
            break
        if not chunk:
            break
        all_trades.extend(chunk)
        if len(chunk) < page_size:
            break
        page += 1

    rel = [t for t in all_trades if t.get("asset") == up_token]
    rel.sort(key=lambda x: x["timestamp"])
    if not rel:
        return (np.array([]),) * 4
    times = np.array([t["timestamp"] for t in rel], dtype=float)
    prices = np.array([t["price"] for t in rel], dtype=float)
    sizes = np.array([t.get("size", 0.0) for t in rel], dtype=float)
    sides = np.array([1 if str(t.get("side", "")).upper() == "BUY" else -1 for t in rel], dtype=np.int8)
    return times, prices, sizes, sides


def fetch_market(slug, force=False):
    """Fetch + cache a single market. Returns market dict or None."""
    path = _market_cache_path(slug)
    if os.path.exists(path) and not force:
        try:
            with gzip.open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass

    ev = fetch_event(slug)
    if not ev or not ev.get("markets") or not ev["markets"][0].get("clobTokenIds"):
        return None
    info = _parse_market(ev)
    market_start = int(slug.split("-")[-1])
    times, prices, sizes, sides = _fetch_trades(info["condition_id"], info["up_token"])

    # Keep trades within the market window (+ small grace for resolution prints)
    mask = (times >= market_start) & (times <= market_start + 360)
    times, prices, sizes, sides = times[mask], prices[mask], sizes[mask], sides[mask]
    if len(times) < MIN_POINTS:
        return None

    rel = times - market_start
    final_mask = (rel >= 290) & (rel <= 310)
    if final_mask.sum() > 0:
        actual_price = float(np.clip(np.mean(prices[final_mask]), 0, 1))
    else:
        actual_price = float(np.clip(prices[-1], 0, 1))

    mkt = {
        "slug": slug,
        "asset": slug.split("-")[0],
        "market_start": market_start,
        "actual_price": actual_price,
        "actual_bin": 1.0 if actual_price >= 0.5 else 0.0,
        "times": times,
        "prices": prices,
        "sizes": sizes,
        "sides": sides,
    }
    try:
        with gzip.open(path, "wb") as f:
            pickle.dump(mkt, f)
    except Exception:
        pass
    return mkt


def build_dataset(name, n, start_offset, asset="btc", max_workers=16, end_ref=None):
    """
    Collect `n` valid markets, scanning backward starting `start_offset` windows
    before the current 5-min boundary (or before `end_ref` unix ts if given).

    Returns the list of market dicts and caches the whole list to
    cache/<name>.pkl.gz.
    """
    bundle_path = os.path.join(CACHE_DIR, f"{name}.pkl.gz")
    if os.path.exists(bundle_path):
        with gzip.open(bundle_path, "rb") as f:
            data = pickle.load(f)
        print(f"[{name}] loaded {len(data)} cached markets")
        return data

    if end_ref is None:
        end_ref = int(time.time())
    base = end_ref - (end_ref % 300)

    # Candidate slugs: over-scan since some markets are missing / empty.
    slugs = [f"{asset}-updown-5m-{base - (start_offset + i) * 300}" for i in range(n * 3)]

    print(f"[{name}] fetching up to {n} markets from {len(slugs)} candidates "
          f"(offset {start_offset}, {max_workers} workers)...")

    collected = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_market, s): s for s in slugs}
        for fut in as_completed(futures):
            mkt = fut.result()
            if mkt is not None:
                collected.append(mkt)
                if len(collected) % 25 == 0:
                    print(f"[{name}]   {len(collected)} markets "
                          f"({time.time()-t0:.0f}s)")
            if len(collected) >= n:
                break
        for fut in futures:
            fut.cancel()

    collected.sort(key=lambda m: m["market_start"])
    collected = collected[:n] if len(collected) > n else collected

    with gzip.open(bundle_path, "wb") as f:
        pickle.dump(collected, f)
    print(f"[{name}] done: {len(collected)} markets in {time.time()-t0:.0f}s -> {bundle_path}")
    return collected


def load_dataset(name):
    bundle_path = os.path.join(CACHE_DIR, f"{name}.pkl.gz")
    with gzip.open(bundle_path, "rb") as f:
        return pickle.load(f)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--n", type=int, default=300)
    p.add_argument("--offset", type=int, default=1)
    p.add_argument("--asset", default="btc")
    p.add_argument("--workers", type=int, default=16)
    args = p.parse_args()
    build_dataset(args.name, args.n, args.offset, args.asset, args.workers)
