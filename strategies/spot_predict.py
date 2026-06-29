#!/usr/bin/env python3
"""
Self-contained live inference for the recommended Combined-Logistic model.

Drop-in alternative to sway_predict.py with the SAME stdin/stdout JSON contract,
except it additionally fetches the underlying BTC spot (Binance BTCUSDT 1s
klines) for the market window — the signal that makes this model robust.

stdin JSON:
  { "times":[...], "prices":[...], "market_start":int, "elapsed":int, "remaining":int }
stdout JSON:
  { "outcome":"UP"|"DOWN", "confidence":float, "raw_prediction":float,
    "features_computed":bool, ... }
"""

import sys
import os
import json
import pickle
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

from features_spot import extract_combined_features  # noqa: E402
from spotcache import symbol_for  # noqa: E402

MODEL_PATH = os.path.join(_DIR, "combined_model_production.pkl")
BINANCE_HOSTS = ["https://api.binance.com", "https://data-api.binance.vision"]


def fetch_spot(market_start, elapsed, symbol="BTCUSDT"):
    """Fetch Binance 1s klines for [market_start, market_start+elapsed] (no look-ahead)."""
    end = market_start + int(elapsed)
    params = {"symbol": symbol, "interval": "1s",
              "startTime": market_start * 1000, "endTime": end * 1000}
    for host in BINANCE_HOSTS:
        try:
            r = requests.get(host + "/api/v3/klines", params=params, timeout=8)
            if r.status_code == 200:
                k = r.json()
                if len(k) < 5:
                    return None
                rel = np.array([row[0] / 1000.0 - market_start for row in k], dtype=float)
                close = np.array([float(row[4]) for row in k], dtype=float)
                return {"market_start": market_start, "rel": rel, "close": close,
                        "open": float(k[0][1])}
        except Exception:
            continue
    return None


def main():
    data = json.load(sys.stdin)
    times = np.array(data["times"], dtype=float)
    prices = np.array(data["prices"], dtype=float)
    market_start = int(data["market_start"])
    elapsed = float(data["elapsed"])
    # asset/symbol: accept "asset" (e.g. "eth") or explicit "symbol" in the
    # payload, else the SWAY_ASSET env var, else default BTC.
    asset = data.get("asset") or os.getenv("SWAY_ASSET", "btc").split(",")[0].strip()
    symbol = data.get("symbol") or symbol_for(asset)

    with open(MODEL_PATH, "rb") as f:
        art = pickle.load(f)
    model, feats = art["model"], art["feature_names"]

    spot = fetch_spot(market_start, elapsed, symbol)
    market = {"times": times, "prices": prices, "sizes": np.zeros_like(prices),
              "sides": np.zeros_like(prices, dtype=np.int8),
              "market_start": market_start, "spot": spot}

    # sizes/sides unknown at inference; combined features that use them degrade
    # gracefully to 0. If size/side are available upstream, pass them through.
    if "sizes" in data:
        market["sizes"] = np.array(data["sizes"], dtype=float)
    if "sides" in data:
        market["sides"] = np.array(data["sides"], dtype=np.int8)

    f = extract_combined_features(market, elapsed) if spot is not None else None
    if f is None:
        json.dump({"outcome": "UNKNOWN", "confidence": 0.0, "raw_prediction": 0.5,
                   "features_computed": False,
                   "error": "no_spot" if spot is None else "insufficient_data"}, sys.stdout)
        return

    x = np.nan_to_num(np.array([[f.get(k, 0.0) for k in feats]], dtype=float))
    p = float(np.clip(model.predict_proba(x)[0, 1], 0.0, 1.0))
    meta = art.get("metadata", {})
    json.dump({
        "outcome": "UP" if p > 0.5 else "DOWN",
        "confidence": round(abs(p - 0.5) * 2.0, 4),
        "raw_prediction": round(p, 4),
        "features_computed": True,
        "spot_lead_bps": round(f.get("spot_lead_bps", 0.0), 2),
        "spot_barrier_prob": round(f.get("spot_barrier_prob", 0.5), 4),
        "market_price": round(f.get("last_price", 0.5), 4),
        "model_strategy": art.get("strategy", ""),
        # model-identity fields (consumed by the Go bot's dashboard/logging)
        "model_version": "combined",
        "model_markets": int(meta.get("trained_on_markets", 0)),
        "model_training_date": str(meta.get("training_date", "")),
    }, sys.stdout)


if __name__ == "__main__":
    main()
