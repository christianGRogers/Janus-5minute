#!/usr/bin/env python3
"""
Retrain the sway model on the latest 600 markets.
Saves to sway_model_live.pkl in the same directory.
Called at startup and after a loss is detected by the Go bot.
"""
import os
import sys
import time
import warnings
warnings.filterwarnings('ignore')

# Allow importing from sway_model.py which lives in the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sway_model import (
    find_historical_markets_v3,
    collect_market_data_v2,
    save_markets_to_csv_v2,
    load_and_prepare_data_v2,
    train_v2_model,
    V2_FEATURE_NAMES,
    V2_REMAINING_TIMES,
)

import numpy as np
import joblib

RETRAIN_MARKETS = 600
_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(_DIR, 'sway_model_live.pkl')
TMP_CSV = os.path.join(_DIR, '_retrain_tmp.csv')


def retrain():
    print(f"[Retrain] Starting retrain on latest {RETRAIN_MARKETS} markets...", flush=True)
    t0 = time.time()

    events = find_historical_markets_v3(total_markets=RETRAIN_MARKETS)
    if not events:
        print("[Retrain] No markets found — aborting.", flush=True)
        return False

    markets_data = collect_market_data_v2(events)
    if not markets_data:
        print("[Retrain] No valid in-window markets — aborting.", flush=True)
        return False

    print(f"[Retrain] Collected {len(markets_data)} markets", flush=True)

    save_markets_to_csv_v2(markets_data, TMP_CSV)

    try:
        X, y, remaining_arr = load_and_prepare_data_v2(TMP_CSV)
    except Exception as e:
        print(f"[Retrain] Feature prep failed: {e}", flush=True)
        return False
    finally:
        if os.path.exists(TMP_CSV):
            os.remove(TMP_CSV)

    models = {}
    for remaining in V2_REMAINING_TIMES:
        model, r2 = train_v2_model(X, y, remaining_arr, remaining)
        if model is not None:
            models[remaining] = {'model': model, 'r2': r2}
            print(f"[Retrain]   {remaining}s remaining: R²={r2:.4f}", flush=True)

    if not models:
        print("[Retrain] No models trained — aborting.", flush=True)
        return False

    avg_r2 = float(np.mean([m['r2'] for m in models.values()]))

    production_model = {
        'models': models,
        'feature_names': V2_FEATURE_NAMES,
        'metadata': {
            'version': 'live',
            'num_markets': len(markets_data),
            'avg_r2': avg_r2,
            'per_slot_r2': {r: models[r]['r2'] for r in models},
            'training_date': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
        },
    }

    # Write atomically: temp file then rename so a mid-train prediction never
    # reads a half-written pkl.
    tmp_out = OUTPUT_PATH + '.tmp'
    joblib.dump(production_model, tmp_out)
    os.replace(tmp_out, OUTPUT_PATH)

    elapsed = time.time() - t0
    print(f"[Retrain] Done in {elapsed:.0f}s | avg R²={avg_r2:.4f} | {OUTPUT_PATH}", flush=True)
    return True


if __name__ == '__main__':
    sys.exit(0 if retrain() else 1)
