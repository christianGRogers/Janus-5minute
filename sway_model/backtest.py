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
# Market Discovery
# ======================================================================

def get_valid_market_slugs(num_markets=10):
    """Get valid market slugs by searching backwards from current time"""
    
    now = int(time.time())
    # Align to 5-minute boundary
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
    
    m, c = np.polyfit(x, y, 1)
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
    
    model = model_data['model']
    feature_names = model_data['feature_names']
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

        # Extract features using ONLY data up to the elapsed point
        features = extract_features_at_prediction_time(
            trades_times, prices, market_start, elapsed
        )

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

        # Create feature vector
        feature_vector = pd.DataFrame([features])
        for col in feature_names:
            if col not in feature_vector.columns:
                feature_vector[col] = 0
        feature_vector = feature_vector[feature_names].fillna(0)

        # Make prediction
        prediction_price = model.predict(feature_vector)[0]
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
        print(f"✓ Model loaded successfully!")
        print(f"  - R² score: {model_data['metadata']['r2_score']:.4f}")
        print(f"  - Training date: {model_data['metadata']['training_date']}")
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
    
    args = parser.parse_args()
    
    if args.list:
        list_available_markets(20)
        return
    
    # Parse prediction times
    prediction_times = [int(t.strip()) for t in args.prediction_times.split(',')]
    
    if args.slug:
        # Test single market
        test_specific_market(args.model, args.slug)
    else:
        # Test multiple markets
        test_multiple_markets(args.model, prediction_times, args.num_markets)

if __name__ == "__main__":
    main()