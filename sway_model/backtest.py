#!/usr/bin/env python3
"""
Historical Market Backtest Script
- Tests trained model on historical markets
- Makes predictions at different times (60s, 30s, 20s, 15s, 10s remaining)
- Only uses data available up to the prediction time (no look-ahead bias)
- Compares predictions to actual outcomes
"""

import argparse
import json
import os
import time
import numpy as np
import pandas as pd
import requests
import joblib
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ======================================================================
# CONFIG
# ======================================================================

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

WINDOW_SIZES = [10, 15, 20, 30, 60]
MIN_POINTS_PER_WINDOW = 3

# ======================================================================
# V2 CONFIG  (must stay in sync with sway_model.py V2_FEATURE_NAMES)
# ======================================================================

ROLLING_STEPS = 5
ROLLING_STEP_SIZE = 5

V2_FEATURE_NAMES = [
    'sway_10s_last', 'sway_10s_mean', 'sway_10s_std', 'sway_10s_trend', 'sway_10s_data_count',
    'sway_15s_last', 'sway_15s_mean', 'sway_15s_std', 'sway_15s_trend', 'sway_15s_data_count',
    'sway_20s_last', 'sway_20s_mean', 'sway_20s_std', 'sway_20s_trend', 'sway_20s_data_count',
    'sway_30s_last', 'sway_30s_mean', 'sway_30s_std', 'sway_30s_trend', 'sway_30s_data_count',
    'sway_60s_last', 'sway_60s_mean', 'sway_60s_std', 'sway_60s_trend', 'sway_60s_data_count',
    'sway_agreement', 'sway_magnitude', 'short_long_div', 'time_remaining',
]

# ======================================================================
# Market Discovery
# ======================================================================

def get_valid_market_slugs(num_markets=10, before_timestamp=None):
    """Get valid market slugs by searching backwards from current time (or before_timestamp)."""

    if before_timestamp is not None:
        current_window = before_timestamp - (before_timestamp % 300)
    else:
        now = int(time.time())
        current_window = now - (now % 300)
    market_slugs = []

    print(f"Searching for {num_markets} valid markets...")
    
    for i in range(1, num_markets * 3):  # Search more to account for missing markets
        market_time = current_window - (i * 300)
        slug = f"btc-updown-5m-{market_time}"
        
        # Check if market exists
        try:
            r = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    market_slugs.append(slug)
                    print(f"  Found: {slug}")
                    
                    if len(market_slugs) >= num_markets:
                        break
        except:
            pass
        
        # Small delay to avoid rate limiting
        time.sleep(0.1)
    
    print(f"\nFound {len(market_slugs)} valid markets")
    return market_slugs

def fetch_market_by_slug(slug):
    """Fetch a specific market by slug"""
    try:
        r = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data[0] if data else None
    except Exception as e:
        return None

def parse_market_info(event):
    """Parse market information from event"""
    market = event["markets"][0]
    condition_id = market["conditionId"]
    token_ids = market["clobTokenIds"]
    
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    
    outcomes = market.get("outcomes", '["Up","Down"]')
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    
    # Find the "Up" outcome index
    up_idx = 0
    for i, outcome in enumerate(outcomes):
        if str(outcome).strip().lower() in ("up", "yes"):
            up_idx = i
            break
    
    return {
        "condition_id": condition_id,
        "outcome_token": token_ids[up_idx],
        "slug": event.get('slug'),
        "title": event.get('title', ''),
    }

def fetch_all_trades(condition_id, token_id):
    """Fetch all trades for a market"""
    all_trades = []
    page = 0
    page_size = 1000
    
    while True:
        try:
            r = requests.get(
                f"{DATA_API}/trades",
                params={
                    "market": condition_id,
                    "limit": page_size,
                    "offset": page * page_size
                },
                timeout=15
            )
            r.raise_for_status()
            chunk = r.json()
            
            if not chunk:
                break
            
            all_trades.extend(chunk)
            
            if len(chunk) < page_size:
                break
                
            page += 1
            
        except Exception as e:
            print(f"  Error fetching trades: {e}")
            break
    
    # Filter for specific token and sort
    relevant = [t for t in all_trades if t.get("asset") == token_id]
    relevant.sort(key=lambda x: x["timestamp"])
    
    if not relevant:
        return np.array([]), np.array([])
    
    times = np.array([t["timestamp"] for t in relevant], dtype=float)
    prices = np.array([t["price"] for t in relevant], dtype=float)
    
    return times, prices

# ======================================================================
# Sway Calculation (using only data up to prediction time)
# ======================================================================

def fit_channel(x, y):
    """Fit linear channel to price data"""
    if len(x) < 2:
        return 0, 0, 0
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        return 0, 0, 0
    if np.ptp(x) == 0:
        return 0, 0, 0
    try:
        m, c = np.polyfit(x, y, 1)
    except (np.linalg.LinAlgError, ValueError):
        return 0, 0, 0
    resid = y - (m * x + c)
    a = c + resid.min()
    b = c + resid.max()
    return m, a, b

def calculate_sway_at_time(times, prices, market_start, prediction_seconds, window_size):
    """
    Calculate sway at a specific prediction time
    IMPORTANT: Only uses data up to prediction_seconds (no look-ahead)
    """
    # Convert to relative times
    rel_times = times - market_start
    
    # CRITICAL: Only use data up to the prediction time
    mask = rel_times <= prediction_seconds
    rel_times_censored = rel_times[mask]
    prices_censored = prices[mask]
    
    if len(rel_times_censored) < MIN_POINTS_PER_WINDOW:
        return np.nan
    
    # Get data within the window
    window_start = prediction_seconds - window_size
    window_mask = (rel_times_censored >= window_start) & (rel_times_censored <= prediction_seconds)
    
    x = rel_times_censored[window_mask] - window_start
    y = prices_censored[window_mask]
    
    if len(x) < MIN_POINTS_PER_WINDOW:
        return np.nan
    
    m, a, b = fit_channel(x, y)
    width = b - a
    
    if width > 1e-9:
        return m / width
    return np.nan

def extract_features_at_prediction_time(times, prices, market_start, prediction_seconds):
    """
    Extract features at a specific prediction time
    CRITICAL: Only uses data available up to prediction_seconds
    """
    # Convert to relative times
    rel_times = times - market_start
    
    # CRITICAL: Only use data up to the prediction time
    mask = rel_times <= prediction_seconds
    rel_times_censored = rel_times[mask]
    prices_censored = prices[mask]
    
    if len(rel_times_censored) < MIN_POINTS_PER_WINDOW:
        return None
    
    features = {
        'prediction_time': prediction_seconds,
        'sample_time': prediction_seconds,
        'time_remaining': 300 - prediction_seconds,
    }
    
    # Calculate sway for each window using only data up to prediction time
    for window in WINDOW_SIZES:
        sway = calculate_sway_at_time(times, prices, market_start, prediction_seconds, window)
        col = f'sway_{window}s'
        
        has_data = 0 if np.isnan(sway) else 1
        
        features[f'{col}_last'] = sway if not np.isnan(sway) else 0
        features[f'{col}_mean'] = sway if not np.isnan(sway) else 0
        features[f'{col}_std'] = 0
        features[f'{col}_trend'] = 0
        features[f'{col}_min'] = sway if not np.isnan(sway) else 0
        features[f'{col}_max'] = sway if not np.isnan(sway) else 0
        features[f'{col}_has_data'] = has_data
        features[f'{col}_data_count'] = has_data
        features[f'{col}_data_ratio'] = has_data
        features[f'{col}_volatility'] = 0
    
    return features

# ======================================================================
# Get Actual Market Outcome
# ======================================================================

def get_actual_outcome(event, times, prices, market_start):
    """
    Determine the actual market outcome (resolution price)
    Uses final price at market end (300 seconds)
    """
    market = event["markets"][0]
    
    # First try to get official outcome
    if market.get('outcome'):
        outcome = market['outcome']
        if outcome.lower() == 'up':
            return 1.0
        elif outcome.lower() == 'down':
            return 0.0
    
    # Otherwise use final price at market end (300 seconds)
    rel_times = times - market_start
    # Look at trades near the end (290-310 seconds)
    final_mask = (rel_times >= 290) & (rel_times <= 310)
    final_prices = prices[final_mask]
    
    if len(final_prices) > 0:
        final_price = np.mean(final_prices)
        return final_price
    
    # Fallback to last trade
    if len(prices) > 0:
        return prices[-1]
    
    return 0.5

# ======================================================================
# V2 Feature Extraction & Model Dispatch
# ======================================================================

def extract_features_v2(times, prices, market_start, elapsed):
    """
    Compute 29 v2 features at `elapsed` seconds from market_start.
    Rolling sway: computed at elapsed, elapsed-5, elapsed-10, elapsed-15, elapsed-20.
    No look-ahead: only trades with rel_time <= elapsed are used.
    Returns dict matching V2_FEATURE_NAMES, or None if insufficient data.
    """
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
            sway = calculate_sway_at_time(times, prices, market_start, step_t, w)
            sway_vals.append(sway)

        valid = [v for v in sway_vals if not np.isnan(v)]
        data_count = len(valid)
        last  = sway_vals[0] if not np.isnan(sway_vals[0]) else 0.0
        mean  = float(np.mean(valid))  if data_count > 0 else 0.0
        std   = float(np.std(valid))   if data_count > 1 else 0.0
        if data_count > 1:
            chrono = list(reversed(valid))           # oldest → newest
            trend = float(np.mean(np.diff(chrono)))  # positive = rising
        else:
            trend = 0.0

        features[f'sway_{w}s_last']       = last
        features[f'sway_{w}s_mean']       = mean
        features[f'sway_{w}s_std']        = std
        features[f'sway_{w}s_trend']      = trend
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


def make_prediction(model_data, features_dict, remaining):
    """
    Dispatch prediction to the correct model based on pkl version.
    v1 pkl: has 'model' key (single model, all timepoints).
    v2 pkl: has 'models' key (dict keyed by remaining time).
    Returns float in [0, 1] or None.
    """
    if 'models' in model_data:
        slot = model_data['models'].get(int(remaining))
        if slot is None:
            return None
        model = slot['model']
        feature_names = model_data['feature_names']
    else:
        model = model_data['model']
        feature_names = model_data['feature_names']

    fv = pd.DataFrame([{k: features_dict.get(k, 0.0) for k in feature_names}])
    fv = fv[feature_names].fillna(0.0)
    return float(np.clip(model.predict(fv)[0], 0.0, 1.0))


# ======================================================================
# Test Single Market at Multiple Prediction Times
# ======================================================================

def test_market_at_prediction_times(model_data, slug, prediction_times=[60, 30, 20, 15, 10]):
    """
    Test a market by making predictions at different points near the end.
    prediction_times = seconds REMAINING in the market (e.g. 60 = predict with 60s left).
    Each prediction only uses data available up to that elapsed point.
    """
    
    print(f"\n{'='*80}")
    print(f"Testing Market: {slug}")
    print(f"{'='*80}")
    
    # Fetch market
    event = fetch_market_by_slug(slug)
    if not event:
        print(f"✗ Market not found")
        return None
    
    market_info = parse_market_info(event)
    print(f"Title: {market_info['title']}")
    
    # Get market start time from slug
    market_timestamp = int(slug.split('-')[-1])
    market_start = market_timestamp
    market_end = market_start + 300
    
    print(f"Market start: {datetime.fromtimestamp(market_start).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Market end: {datetime.fromtimestamp(market_end).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Fetch all trades
    trades_times, prices = fetch_all_trades(market_info['condition_id'], market_info['outcome_token'])
    
    if len(trades_times) == 0:
        print(f"✗ No trades found")
        return None
    
    # Calculate relative times
    rel_times = trades_times - market_start
    first_trade = rel_times[0]
    last_trade = rel_times[-1]
    
    print(f"Total trades: {len(trades_times)}")
    print(f"First trade: {first_trade:.1f}s into market")
    print(f"Last trade: {last_trade:.1f}s into market")
    
    # Get actual outcome
    actual_price = get_actual_outcome(event, trades_times, prices, market_start)
    actual_outcome = "UP" if actual_price >= 0.5 else "DOWN"
    
    print(f"\nActual resolution: {actual_outcome} (price: {actual_price:.3f})")
    
    # Make predictions at each specified time
    print(f"\n{'='*80}")
    print(f"PREDICTIONS (using only data available up to each prediction time)")
    print(f"{'='*80}")
    
    version = model_data.get('metadata', {}).get('version', 1)
    results = []

    for pred_remaining in prediction_times:
        # Convert remaining seconds to elapsed seconds from market start
        elapsed = 300 - pred_remaining

        # Check if we have data up to the required elapsed point
        if last_trade < elapsed:
            print(f"\n{pred_remaining}s remaining: ⚠️ No data available (last trade at {last_trade:.1f}s elapsed)")
            continue

        print(f"\n{'='*60}")
        print(f"Predicting with {pred_remaining}s remaining ({elapsed}s elapsed)")
        print(f"{'='*60}")

        # Extract features using the right method for this model version
        if version >= 2:
            features = extract_features_v2(trades_times, prices, market_start, elapsed)
        else:
            features = extract_features_at_prediction_time(trades_times, prices, market_start, elapsed)

        if features is None:
            print(f"  ✗ Insufficient data for prediction")
            continue

        # Calculate available trades up to this point
        trades_up_to_point = np.sum(rel_times <= elapsed)
        print(f"  Trades available: {trades_up_to_point}")

        # Calculate sway values (show which windows have data)
        print(f"  Sway values:")
        sway_count = 0
        for window in WINDOW_SIZES:
            sway = calculate_sway_at_time(trades_times, prices, market_start, elapsed, window)
            if not np.isnan(sway):
                print(f"    {window}s: {sway:+.4f}")
                sway_count += 1
            else:
                print(f"    {window}s: insufficient data")

        if sway_count == 0:
            print(f"  ⚠️ No sway values available, prediction may be unreliable")

        # Make prediction via dispatcher (handles v1 single model and v2+ per-slot models)
        prediction_price = make_prediction(model_data, features, pred_remaining)
        if prediction_price is None:
            print(f"  ✗ No model slot for {pred_remaining}s remaining")
            continue
        prediction_price = np.clip(prediction_price, 0, 1)
        predicted_outcome = "UP" if prediction_price >= 0.5 else "DOWN"
        confidence = abs(prediction_price - 0.5) * 2

        # Check if correct
        correct = (prediction_price >= 0.5) == (actual_price >= 0.5)

        print(f"\n  Prediction:")
        print(f"    Predicted resolution price: {prediction_price:.3f}")
        print(f"    Predicted outcome: {predicted_outcome}")
        print(f"    Confidence: {confidence:.1%}")
        print(f"    Correct: {'✓ YES' if correct else '✗ NO'}")

        results.append({
            'prediction_time': pred_remaining,
            'trades_available': trades_up_to_point,
            'predicted_price': prediction_price,
            'predicted_outcome': predicted_outcome,
            'confidence': confidence,
            'actual_price': actual_price,
            'actual_outcome': actual_outcome,
            'correct': correct
        })
    
    return {
        'slug': slug,
        'market_start': market_start,
        'total_trades': len(trades_times),
        'actual_price': actual_price,
        'actual_outcome': actual_outcome,
        'predictions': results
    }

# ======================================================================
# Test Multiple Markets
# ======================================================================

def test_multiple_markets(model_path='sway_model_production.pkl', 
                          prediction_times=[60, 30, 20, 15, 10],
                          num_markets=10):
    """Test model on multiple historical markets"""
    
    print("="*80)
    print("HISTORICAL MARKET BACKTEST (No Look-Ahead Bias)")
    print("="*80)
    print(f"Prediction times: {prediction_times} seconds REMAINING in market")
    print(f"Each prediction only uses data available up to that elapsed point")
    print("="*80)
    
    # Load model
    print(f"\nLoading model from {model_path}...")
    try:
        model_data = joblib.load(model_path)
        meta = model_data.get('metadata', {})
        print(f"✓ Model loaded successfully!")
        print(f"  - Version: v{meta.get('version', 1)}")
        print(f"  - Markets: {meta.get('num_markets', '?')}")
        r2 = meta.get('avg_r2', meta.get('r2_score', '?'))
        print(f"  - Avg R²: {r2}")
        print(f"  - Training date: {meta.get('training_date', '?')}")
    except Exception as e:
        print(f"✗ Error loading model: {e}")
        return
    
    # Get valid market slugs
    market_slugs = get_valid_market_slugs(num_markets)
    
    if not market_slugs:
        print("No valid markets found")
        return
    
    # Test each market
    all_results = []
    
    for slug in market_slugs:
        result = test_market_at_prediction_times(model_data, slug, prediction_times)
        if result and result['predictions']:
            all_results.append(result)
        time.sleep(1)  # Rate limiting
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    if all_results:
        # Compile results by prediction time
        for pred_time in prediction_times:
            print(f"\n{'='*60}")
            print(f"PREDICTIONS AT {pred_time}s REMAINING")
            print(f"{'='*60}")
            
            correct_count = 0
            total_count = 0
            confidences = []
            
            for result in all_results:
                for pred in result['predictions']:
                    if pred['prediction_time'] == pred_time:
                        total_count += 1
                        if pred['correct']:
                            correct_count += 1
                        confidences.append(pred['confidence'])
                        
                        # Show individual results
                        symbol = "✓" if pred['correct'] else "✗"
                        print(f"{symbol} {result['slug'][-20:]}: {pred['predicted_outcome']} "
                              f"(conf: {pred['confidence']:.1%}) | Actual: {pred['actual_outcome']}")
            
            if total_count > 0:
                accuracy = correct_count / total_count
                avg_confidence = np.mean(confidences)
                print(f"\n  Accuracy: {accuracy:.1%} ({correct_count}/{total_count})")
                print(f"  Avg Confidence: {avg_confidence:.1%}")
                
                # Confidence calibration
                high_conf = [c for c in confidences if c > 0.7]
                if high_conf:
                    print(f"  High confidence predictions (>70%): {len(high_conf)}")
        
        # Overall summary
        print("\n" + "="*80)
        print("OVERALL PERFORMANCE")
        print("="*80)
        
        all_predictions = []
        for result in all_results:
            for pred in result['predictions']:
                all_predictions.append(pred)
        
        if all_predictions:
            df = pd.DataFrame(all_predictions)
            overall_accuracy = df['correct'].mean()
            print(f"Total predictions: {len(df)}")
            print(f"Overall accuracy: {overall_accuracy:.1%}")
            print(f"\nAccuracy by prediction time:")
            for pred_time in prediction_times:
                time_df = df[df['prediction_time'] == pred_time]
                if len(time_df) > 0:
                    acc = time_df['correct'].mean()
                    print(f"  {pred_time}s remaining: {acc:.1%} ({len(time_df)} predictions)")
    else:
        print("No successful tests completed")

# ======================================================================
# V2 Comparison
# ======================================================================

def test_market_comparison(model_v1, model_v2, slug, prediction_times=[60, 30, 20, 15, 10]):
    """
    Run both v1 and v2 models on one market.
    v1 uses extract_features_at_prediction_time; v2 uses extract_features_v2.
    Returns side-by-side prediction results.
    """
    event = fetch_market_by_slug(slug)
    if not event:
        return None

    market_info = parse_market_info(event)
    market_start = int(slug.split('-')[-1])

    times, prices = fetch_all_trades(market_info['condition_id'], market_info['outcome_token'])
    if len(times) == 0:
        return None

    rel_times = times - market_start
    actual_price = get_actual_outcome(event, times, prices, market_start)
    actual_outcome = "UP" if actual_price >= 0.5 else "DOWN"

    predictions = []
    for remaining in prediction_times:
        elapsed = 300 - remaining

        if rel_times[-1] < elapsed:
            continue

        trades_at_point = int(np.sum(rel_times <= elapsed))

        # V1
        v1_pred = None
        v1_feat = extract_features_at_prediction_time(times, prices, market_start, elapsed)
        if v1_feat is not None:
            v1_pred = make_prediction(model_v1, v1_feat, remaining)

        # V2
        v2_pred = None
        v2_feat = extract_features_v2(times, prices, market_start, elapsed)
        if v2_feat is not None:
            v2_pred = make_prediction(model_v2, v2_feat, remaining)

        predictions.append({
            'remaining': remaining,
            'trades_available': trades_at_point,
            'actual_price': actual_price,
            'actual_outcome': actual_outcome,
            'v1_pred': v1_pred,
            'v1_outcome': ("UP" if v1_pred >= 0.5 else "DOWN") if v1_pred is not None else None,
            'v1_correct': bool((v1_pred >= 0.5) == (actual_price >= 0.5)) if v1_pred is not None else None,
            'v1_confidence': abs(v1_pred - 0.5) * 2 if v1_pred is not None else None,
            'v2_pred': v2_pred,
            'v2_outcome': ("UP" if v2_pred >= 0.5 else "DOWN") if v2_pred is not None else None,
            'v2_correct': bool((v2_pred >= 0.5) == (actual_price >= 0.5)) if v2_pred is not None else None,
            'v2_confidence': abs(v2_pred - 0.5) * 2 if v2_pred is not None else None,
        })

    return {
        'slug': slug,
        'actual_price': actual_price,
        'actual_outcome': actual_outcome,
        'predictions': predictions,
    }


def compare_models(model1_path, model2_path, num_markets=20, prediction_times=[60, 30, 20, 15, 10], before_timestamp=None):
    """Run both models on the same markets and print a side-by-side accuracy table."""
    print("=" * 80)
    print("MODEL COMPARISON BACKTEST")
    print("=" * 80)
    print(f"V1: {model1_path}")
    print(f"V2: {model2_path}")
    print("=" * 80)

    import warnings
    warnings.filterwarnings('ignore')

    model_v1 = joblib.load(model1_path)
    model_v2 = joblib.load(model2_path)

    v1_meta = model_v1.get('metadata', {})
    v2_meta = model_v2.get('metadata', {})
    print(f"\nV1 metadata: markets={v1_meta.get('num_markets','?')}  "
          f"R²={v1_meta.get('r2_score', v1_meta.get('avg_r2','?'))}")
    print(f"V2 metadata: markets={v2_meta.get('num_markets','?')}  "
          f"avg R²={v2_meta.get('avg_r2','?'):.4f}  "
          f"per-slot={v2_meta.get('per_slot_r2',{})}")

    market_slugs = get_valid_market_slugs(num_markets, before_timestamp=before_timestamp)
    if not market_slugs:
        print("No markets found")
        return

    all_results = []
    for slug in market_slugs:
        print(f"  Testing {slug[-25:]}...", end=' ', flush=True)
        result = test_market_comparison(model_v1, model_v2, slug, prediction_times)
        if result and result['predictions']:
            all_results.append(result)
            print(f"actual={result['actual_outcome']}")
        else:
            print("skipped")
        time.sleep(1)

    if not all_results:
        print("No results to report")
        return

    # Count actuals for base-rate
    actuals = [r['actual_outcome'] for r in all_results]
    down_count = actuals.count('DOWN')
    base_rate = down_count / len(actuals)
    print(f"\nBase rate: {down_count}/{len(actuals)} DOWN ({base_rate:.1%})")
    print(f"Naive always-DOWN accuracy: {base_rate:.1%}")

    print(f"\n{'='*80}")
    print(f"{'Time Rem':>10} | {'V1 Acc':>8} | {'V2 Acc':>8} | {'V1 Conf':>8} | {'V2 Conf':>8} | {'n':>4}")
    print(f"{'='*80}")

    for remaining in prediction_times:
        v1_correct = v1_total = v2_correct = v2_total = 0
        v1_confs, v2_confs = [], []

        for r in all_results:
            for p in r['predictions']:
                if p['remaining'] != remaining:
                    continue
                if p['v1_correct'] is not None:
                    v1_total += 1
                    v1_correct += int(p['v1_correct'])
                    v1_confs.append(p['v1_confidence'])
                if p['v2_correct'] is not None:
                    v2_total += 1
                    v2_correct += int(p['v2_correct'])
                    v2_confs.append(p['v2_confidence'])

        v1_acc  = f"{v1_correct/v1_total:.1%}" if v1_total else "N/A"
        v2_acc  = f"{v2_correct/v2_total:.1%}" if v2_total else "N/A"
        v1_conf = f"{np.mean(v1_confs):.1%}" if v1_confs else "N/A"
        v2_conf = f"{np.mean(v2_confs):.1%}" if v2_confs else "N/A"
        n = max(v1_total, v2_total)
        print(f"{remaining:>8}s rem | {v1_acc:>8} | {v2_acc:>8} | {v1_conf:>8} | {v2_conf:>8} | {n:>4}")

    # Totals
    v1_all_c = v1_all_t = v2_all_c = v2_all_t = 0
    for r in all_results:
        for p in r['predictions']:
            if p['v1_correct'] is not None:
                v1_all_t += 1; v1_all_c += int(p['v1_correct'])
            if p['v2_correct'] is not None:
                v2_all_t += 1; v2_all_c += int(p['v2_correct'])

    print(f"{'='*80}")
    v1_oa = f"{v1_all_c/v1_all_t:.1%}" if v1_all_t else "N/A"
    v2_oa = f"{v2_all_c/v2_all_t:.1%}" if v2_all_t else "N/A"
    print(f"{'OVERALL':>10} | {v1_oa:>8} | {v2_oa:>8} | {'':>8} | {'':>8} | {max(v1_all_t,v2_all_t):>4}")
    print(f"Base rate (always-DOWN): {base_rate:.1%}")


# ======================================================================
# Full Model Benchmark
# ======================================================================

def benchmark_all_models(num_markets=30, prediction_times=[60, 30, 20, 15, 10], before_timestamp=None):
    """
    Discover all sway_model*_production.pkl files, run them on the same set of
    live markets, and print accuracy / Brier / confidence tables with a ranking.
    """
    import glob as _glob
    import re as _re

    model_files = sorted(_glob.glob('sway_model*_production.pkl'))
    if not model_files:
        print("No sway_model*_production.pkl files found in current directory.")
        return

    print("=" * 80)
    print("FULL MODEL BENCHMARK  (all versions, same markets)")
    print("=" * 80)

    # Load models and assign short labels
    models = {}
    for path in model_files:
        try:
            m = joblib.load(path)
        except Exception as e:
            print(f"  {path}: load error — {e}")
            continue
        meta = m.get('metadata', {})
        ver = meta.get('version')
        if ver is not None:
            label = f"v{ver}"
        else:
            match = _re.search(r'v(\d+)', os.path.basename(path))
            label = f"v{match.group(1)}" if match else 'orig'
        # Deduplicate: if label already taken, append file suffix
        if label in models:
            label = label + '_b'
        models[label] = m
        ov = meta.get('holdout_scores', {}).get('overall', {})
        stored = (f"stored acc={ov['accuracy']:.3f} brier={ov['brier']:.4f}"
                  if ov else "no stored holdout")
        print(f"  {label:>6}  {os.path.basename(path):<38}  {stored}")

    if not models:
        print("No models loaded.")
        return

    # Fetch a shared set of recent completed markets
    market_slugs = get_valid_market_slugs(num_markets, before_timestamp=before_timestamp)
    if not market_slugs:
        print("No markets found.")
        return

    labels = list(models.keys())

    # Accumulators: {label: {remaining: {correct, brier_sum, confs, n}}}
    acc = {lbl: {t: {'correct': 0, 'brier': 0.0, 'confs': [], 'n': 0}
                 for t in prediction_times}
           for lbl in labels}
    actuals = []

    print(f"\nTesting {len(market_slugs)} markets × {len(labels)} models...\n")

    for slug in market_slugs:
        print(f"  {slug[-25:]}", end='  ', flush=True)

        event = fetch_market_by_slug(slug)
        if not event:
            print("not found")
            continue

        market_info = parse_market_info(event)
        market_start = int(slug.split('-')[-1])
        times, prices = fetch_all_trades(market_info['condition_id'], market_info['outcome_token'])

        if len(times) == 0:
            print("no trades")
            continue

        actual_price = get_actual_outcome(event, times, prices, market_start)
        actual_bin   = 1.0 if actual_price >= 0.5 else 0.0
        actual_out   = "UP" if actual_price >= 0.5 else "DOWN"
        actuals.append(actual_out)
        rel_times = times - market_start

        row_parts = [f"actual={actual_out}"]
        for lbl, model_data in models.items():
            version = model_data.get('metadata', {}).get('version', 1)
            for remaining in prediction_times:
                elapsed = 300 - remaining
                if len(rel_times) == 0 or rel_times[-1] < elapsed:
                    continue
                if version >= 2:
                    features = extract_features_v2(times, prices, market_start, elapsed)
                else:
                    features = extract_features_at_prediction_time(times, prices, market_start, elapsed)
                if features is None:
                    continue
                pred = make_prediction(model_data, features, remaining)
                if pred is None:
                    continue
                pred = float(np.clip(pred, 0.0, 1.0))
                acc[lbl][remaining]['correct'] += int((pred >= 0.5) == (actual_price >= 0.5))
                acc[lbl][remaining]['brier']   += (pred - actual_bin) ** 2
                acc[lbl][remaining]['confs'].append(abs(pred - 0.5) * 2)
                acc[lbl][remaining]['n']       += 1

        print(' | '.join(row_parts))
        time.sleep(0.5)

    # ── Base rate ─────────────────────────────────────────────────────────
    n_mkts = len(actuals)
    down_n = actuals.count('DOWN')
    base   = down_n / n_mkts if n_mkts else 0
    print(f"\nMarkets tested: {n_mkts}  |  DOWN={down_n}  UP={n_mkts-down_n}  "
          f"base rate always-DOWN: {base:.1%}")

    col_w = max(9, max(len(l) for l in labels) + 1)

    def _fmt_header():
        h = f"{'Slot':>10}"
        for lbl in labels:
            h += f"  {lbl:>{col_w}}"
        return h

    def _print_table(title, getter):
        print(f"\n{'='*80}")
        print(title)
        print('='*80)
        hdr = _fmt_header()
        print(hdr)
        print('-' * len(hdr))
        for remaining in prediction_times:
            row = f"{str(remaining)+'s rem':>10}"
            for lbl in labels:
                s = acc[lbl][remaining]
                row += f"  {getter(s):>{col_w}}"
            print(row)
        # Overall row
        print('-' * len(hdr))
        row = f"{'OVERALL':>10}"
        for lbl in labels:
            totals = {'correct': sum(acc[lbl][t]['correct'] for t in prediction_times),
                      'brier':   sum(acc[lbl][t]['brier']   for t in prediction_times),
                      'n':       sum(acc[lbl][t]['n']        for t in prediction_times),
                      'confs':   [c for t in prediction_times for c in acc[lbl][t]['confs']]}
            row += f"  {getter(totals):>{col_w}}"
        print(row)

    def acc_str(s):
        return f"{s['correct']/s['n']:.1%}" if s['n'] else 'N/A'

    def brier_str(s):
        return f"{s['brier']/s['n']:.4f}" if s['n'] else 'N/A'

    def conf_str(s):
        return f"{np.mean(s['confs']):.1%}" if s.get('confs') else 'N/A'

    _print_table("ACCURACY  (higher is better)", acc_str)
    _print_table("BRIER SCORE  (lower is better)", brier_str)
    _print_table("AVG CONFIDENCE", conf_str)

    # ── Ranking summary ───────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print("RANKING SUMMARY")
    print('='*80)

    ranking = []
    for lbl in labels:
        tc = sum(acc[lbl][t]['correct'] for t in prediction_times)
        tb = sum(acc[lbl][t]['brier']   for t in prediction_times)
        tn = sum(acc[lbl][t]['n']       for t in prediction_times)
        if tn > 0:
            ranking.append({'label': lbl, 'accuracy': tc/tn, 'brier': tb/tn, 'n': tn})

    ranking.sort(key=lambda x: (-x['accuracy'], x['brier']))
    print(f"{'Rank':>5}  {'Model':>8}  {'Accuracy':>10}  {'Brier':>10}  {'n':>6}")
    print('-' * 50)
    for i, r in enumerate(ranking, 1):
        tag = '  <- BEST' if i == 1 else ''
        print(f"{i:>5}  {r['label']:>8}  {r['accuracy']:>9.1%}  {r['brier']:>10.4f}  {r['n']:>6}{tag}")


# ======================================================================
# Test Specific Market
# ======================================================================

def test_specific_market(model_path='sway_model_production.pkl', slug=None):
    """Test a specific market"""
    
    if not slug:
        print("Please provide a market slug")
        return
    
    # Load model
    try:
        model_data = joblib.load(model_path)
        test_market_at_prediction_times(model_data, slug)
    except Exception as e:
        print(f"Error: {e}")

# ======================================================================
# List Available Markets
# ======================================================================

def list_available_markets(num_markets=20):
    """List available markets for testing"""
    print("="*80)
    print("AVAILABLE MARKETS")
    print("="*80)
    
    now = int(time.time())
    current_window = now - (now % 300)
    
    found = []
    for i in range(1, num_markets + 1):
        market_time = current_window - (i * 300)
        slug = f"btc-updown-5m-{market_time}"
        
        # Quick check if market exists
        try:
            r = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data and len(data) > 0:
                    found.append(slug)
                    print(f"✓ {slug}")
                else:
                    print(f"✗ {slug} (no data)")
            else:
                print(f"✗ {slug} (not found)")
        except:
            print(f"✗ {slug} (error)")
        
        time.sleep(0.1)
    
    print(f"\nFound {len(found)} markets out of {num_markets} checked")

# ======================================================================
# Main
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description='Test sway model on historical markets (no look-ahead bias)')
    parser.add_argument('--model', default='sway_model_production.pkl', 
                       help='Path to trained model file')
    parser.add_argument('--slug', type=str, 
                       help='Specific market slug to test')
    parser.add_argument('--num_markets', type=int, default=10,
                       help='Number of markets to test')
    parser.add_argument('--prediction_times', type=str, default='60,30,20,15,10',
                       help='Comma-separated list of seconds REMAINING in market when prediction is made')
    parser.add_argument('--list', action='store_true',
                       help='List available markets without testing')
    parser.add_argument('--model2', type=str, default=None,
                       help='Second model path for side-by-side comparison')
    parser.add_argument('--compare', action='store_true',
                       help='Compare --model vs --model2 on same markets')
    parser.add_argument('--before', type=int, default=None,
                       help='Only test markets with timestamp before this Unix time (for OOS testing)')
    parser.add_argument('--benchmark-all', action='store_true',
                       help='Benchmark all sway_model*_production.pkl files on the same markets')

    args = parser.parse_args()

    if args.list:
        list_available_markets(20)
        return

    prediction_times = [int(t.strip()) for t in args.prediction_times.split(',')]

    if args.benchmark_all:
        benchmark_all_models(args.num_markets, prediction_times, before_timestamp=args.before)
        return

    if args.compare:
        if not args.model2:
            print("--compare requires --model2")
            return
        compare_models(args.model, args.model2, args.num_markets, prediction_times,
                       before_timestamp=args.before)
        return

    if args.slug:
        test_specific_market(args.model, args.slug)
    else:
        test_multiple_markets(args.model, prediction_times, args.num_markets)

if __name__ == "__main__":
    main()