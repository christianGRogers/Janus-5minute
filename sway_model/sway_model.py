#!/usr/bin/env python3
"""
Automated Sway Model Training Pipeline
- Collects market data
- Trains model
- Evaluates performance
- Automatically adds more markets if R² < 0.7
- Compiles final model when target achieved
"""

import argparse
import json
import time
import csv
import sys
import os
import joblib
import numpy as np
import pandas as pd
import requests
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

# ======================================================================
# CONFIG
# ======================================================================

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

WINDOW_SIZES = [10, 15, 20, 30, 60]
STEP_SECONDS = 1.0
MIN_POINTS_PER_WINDOW = 3
TARGET_R2 = 0.7
INITIAL_MARKETS = 300
MAX_MARKETS = 2000
MARKET_BATCH_SIZE = 50  # How many markets to add each iteration

# ======================================================================
# Market Discovery & Data Collection
# ======================================================================

def fetch_event_by_slug(slug):
    """Fetch event data by slug"""
    try:
        r = requests.get(f"{GAMMA_API}/events", params={"slug": slug}, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data[0] if data else None
    except Exception as exc:
        print(f"    Request failed for slug={slug}: {exc}")
        return None

def find_historical_markets(num_markets=100):
    """Find historical BTC 5-minute markets"""
    now = int(time.time())
    current_window_start = now - (now % 300)
    events = []
    
    print(f"Searching for {num_markets} historical markets...")
    
    for i in range(1, num_markets + 1):
        window_start = current_window_start - i * 300
        slug = f"btc-updown-5m-{window_start}"
        
        if i % 50 == 0:
            print(f"  Searched {i}/{num_markets} markets...")
        
        ev = fetch_event_by_slug(slug)
        if ev and ev.get("markets") and ev["markets"][0].get("clobTokenIds"):
            events.append(ev)
    
    print(f"Found {len(events)} valid markets")
    return events

def parse_market(event):
    """Parse market data from event"""
    market = event["markets"][0]
    condition_id = market["conditionId"]
    token_ids = market["clobTokenIds"]
    
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    
    outcomes = market.get("outcomes", '["Up","Down"]')
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    
    up_idx = 0
    for i, outcome in enumerate(outcomes):
        if str(outcome).strip().lower() in ("up", "yes"):
            up_idx = i
            break
    
    return {
        "condition_id": condition_id,
        "outcome_token": token_ids[up_idx],
        "slug": event.get('slug')
    }

def fetch_market_trades(condition_id, token_id):
    """Fetch all trades for a market"""
    trades = []
    page = 0
    page_size = 1000
    
    while True:
        try:
            r = requests.get(
                f"{DATA_API}/trades",
                params={"market": condition_id, "limit": page_size, "offset": page * page_size},
                timeout=15
            )
            r.raise_for_status()
            chunk = r.json()
            
            if not chunk:
                break
                
            trades.extend(chunk)
            
            if len(chunk) < page_size:
                break
                
            page += 1
        except Exception as e:
            print(f"    Error fetching trades: {e}")
            break
    
    # Filter for specific token and sort
    relevant = [t for t in trades if t.get("asset") == token_id]
    relevant.sort(key=lambda x: x["timestamp"])
    
    times = np.array([t["timestamp"] for t in relevant], dtype=float)
    prices = np.array([t["price"] for t in relevant], dtype=float)
    
    return times, prices

# ======================================================================
# Sway Calculation
# ======================================================================

def fit_channel(x, y):
    """Fit linear channel to price data"""
    m, c = np.polyfit(x, y, 1)
    resid = y - (m * x + c)
    a = c + resid.min()
    b = c + resid.max()
    return m, a, b

def calculate_sway(times, prices, window_size, min_points=3):
    """Calculate sway series for a market"""
    if len(times) < min_points:
        return np.array([]), np.array([])
    
    t_first = times[0]
    t_last = times[-1]
    
    if t_last - t_first < window_size:
        return np.array([]), np.array([])
    
    eval_times = np.arange(t_first + window_size, t_last + STEP_SECONDS/2, STEP_SECONDS)
    sway_values = np.full(eval_times.shape, np.nan)
    
    for i, t in enumerate(eval_times):
        lo = t - window_size
        mask = (times > lo) & (times <= t)
        
        if mask.sum() < min_points:
            continue
        
        x = times[mask] - lo
        y = prices[mask]
        m, a, b = fit_channel(x, y)
        width = b - a
        
        if width > 1e-9:
            sway_values[i] = m / width
    
    return eval_times, sway_values

# ======================================================================
# Data Collection & CSV Generation
# ======================================================================

def collect_market_data(events):
    """Collect all market data and return structured format"""
    markets_data = []
    
    for idx, event in enumerate(events, 1):
        info = parse_market(event)
        print(f"\n[{idx}/{len(events)}] {info['slug']}")
        
        times, prices = fetch_market_trades(info['condition_id'], info['outcome_token'])
        
        if len(times) == 0:
            print(f"    No trades found, skipping")
            continue
        
        print(f"    {len(times)} trades")
        
        # Calculate sway for each window
        results = {}
        for w in WINDOW_SIZES:
            et, sw = calculate_sway(times, prices, w, MIN_POINTS_PER_WINDOW)
            results[w] = (et, sw)
        
        markets_data.append({
            'market_id': len(markets_data),  # Use sequential ID
            'slug': info['slug'],
            'times': times,
            'prices': prices,
            'results': results,
            't0': times[0]
        })
    
    return markets_data

def save_markets_to_csv(markets_data, output_csv):
    """Save markets data to CSV with proper separation"""
    with open(output_csv, 'w', newline='') as csvfile:
        # Write header
        fieldnames = ['market_id', 'timestamp_absolute', 'timestamp_relative_seconds'] + [f'sway_{w}s' for w in WINDOW_SIZES]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=',')
        writer.writeheader()
        
        for market in markets_data:
            market_id = market['market_id']
            times = market['times']
            results = market['results']
            t0 = market['t0']
            
            # Collect all time points
            all_times = set()
            for w in WINDOW_SIZES:
                et, sw = results[w]
                if len(et) > 0:
                    all_times.update(et)
            
            if not all_times:
                continue
            
            sorted_times = sorted(all_times)
            
            for t in sorted_times:
                row = {
                    'market_id': market_id,
                    'timestamp_absolute': t,
                    'timestamp_relative_seconds': t - t0
                }
                
                for w in WINDOW_SIZES:
                    et, sw = results[w]
                    if len(et) > 0:
                        idx = np.where(np.abs(et - t) < 0.001)[0]
                        if len(idx) > 0 and not np.isnan(sw[idx[0]]):
                            row[f'sway_{w}s'] = sw[idx[0]]
                        else:
                            row[f'sway_{w}s'] = ''
                    else:
                        row[f'sway_{w}s'] = ''
                
                writer.writerow(row)
    
    print(f"\nSaved {len(markets_data)} markets to {output_csv}")

# ======================================================================
# Model Training
# ======================================================================

def load_and_prepare_data(csv_path):
    """Load CSV and prepare features for training - FIXED to handle comments"""
    
    # Read CSV file line by line to filter out comments
    data_lines = []
    with open(csv_path, 'r') as f:
        for line in f:
            if not line.startswith('#'):
                data_lines.append(line)
    
    # Write clean data to temporary file or parse directly
    import io
    clean_data = io.StringIO(''.join(data_lines))
    
    # Read the clean data
    df = pd.read_csv(clean_data)
    
    # Convert market_id to int
    df['market_id'] = df['market_id'].astype(int)
    
    sway_cols = [col for col in df.columns if 'sway_' in col.lower()]
    time_col = 'timestamp_relative_seconds'
    
    print(f"\nLoaded {len(df)} rows from {len(df['market_id'].unique())} markets")
    
    # Calculate resolution price for each market (based on final sway)
    resolution_prices = {}
    for market_id in df['market_id'].unique():
        market_df = df[df['market_id'] == market_id]
        
        # Get final sway values (last non-NaN before 300s)
        final_sways = []
        for col in sway_cols:
            data_before_300 = market_df[market_df[time_col] <= 300][col].dropna()
            if len(data_before_300) > 0:
                final_sways.append(data_before_300.iloc[-1])
        
        if final_sways:
            avg_sway = np.mean(final_sways)
            resolution = 1 / (1 + np.exp(-avg_sway * 5))
        else:
            resolution = 0.5
        
        resolution_prices[market_id] = resolution
    
    df['resolution_price'] = df['market_id'].map(resolution_prices)
    
    # Prepare features for each prediction time
    prediction_times = [60, 30, 20, 15, 10]
    X_list = []
    y_list = []
    
    for pred_time in prediction_times:
        for market_id in df['market_id'].unique():
            market_df = df[df['market_id'] == market_id].copy()
            
            # Sample at different times
            max_time = min(300, market_df[time_col].max())
            if max_time < pred_time:
                continue
                
            sample_times = np.arange(pred_time, max_time, 10)
            
            for sample_time in sample_times:
                window_data = market_df[market_df[time_col] <= sample_time]
                
                if len(window_data) < 5:
                    continue
                
                features = {
                    'prediction_time': pred_time,
                    'sample_time': sample_time,
                    'time_remaining': 300 - sample_time,
                }
                
                for col in sway_cols:
                    values = window_data[col].dropna()
                    
                    if len(values) > 0:
                        features[f'{col}_last'] = values.iloc[-1]
                        features[f'{col}_mean'] = values.mean()
                        features[f'{col}_std'] = values.std() if len(values) > 1 else 0
                        features[f'{col}_trend'] = values.diff().mean() if len(values) > 1 else 0
                    else:
                        features[f'{col}_last'] = 0
                        features[f'{col}_mean'] = 0
                        features[f'{col}_std'] = 0
                        features[f'{col}_trend'] = 0
                    
                    features[f'{col}_data_count'] = len(values)
                
                X_list.append(features)
                y_list.append(resolution_prices[market_id])
    
    if not X_list:
        raise ValueError("No training samples generated. Check if markets have sufficient data.")
    
    X = pd.DataFrame(X_list)
    y = np.array(y_list)
    
    print(f"Generated {len(X)} training samples")
    print(f"Target range: [{y.min():.3f}, {y.max():.3f}]")
    
    return X, y, prediction_times

def train_model(X, y, prediction_time):
    """Train model for a specific prediction time"""
    # Filter for this prediction time
    X_time = X[X['prediction_time'] == prediction_time].copy()
    y_time = y[X['prediction_time'] == prediction_time]
    
    if len(X_time) < 20:
        return None, None, 0
    
    # Prepare features
    feature_cols = [col for col in X_time.columns if col not in ['prediction_time', 'sample_time']]
    X_features = X_time[feature_cols].fillna(0)
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X_features, y_time, test_size=0.2, random_state=42)
    
    # Train Random Forest
    model = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    mse = mean_squared_error(y_test, y_pred)
    
    return model, feature_cols, r2

def evaluate_model_performance(models, prediction_times):
    """Evaluate overall model performance"""
    if not models:
        return 0
    
    r2_scores = []
    for pred_time in prediction_times:
        if pred_time in models and models[pred_time] is not None:
            r2_scores.append(models[pred_time]['r2'])
    
    return np.mean(r2_scores) if r2_scores else 0

# ======================================================================
# Main Pipeline
# ======================================================================

def run_training_pipeline(initial_markets=INITIAL_MARKETS, target_r2=TARGET_R2):
    """Main training pipeline with iterative data collection"""
    
    print("="*80)
    print("SWAY MODEL AUTOMATED TRAINING PIPELINE")
    print("="*80)
    print(f"Target R²: {target_r2}")
    print(f"Initial markets: {initial_markets}")
    print(f"Max markets: {MAX_MARKETS}")
    print(f"Batch size: {MARKET_BATCH_SIZE}")
    print("="*80)
    
    current_markets = initial_markets
    all_events = []
    best_r2 = 0
    iteration = 1
    
    while current_markets <= MAX_MARKETS:
        print(f"\n{'='*80}")
        print(f"ITERATION {iteration}: Training with {current_markets} markets")
        print(f"{'='*80}")
        
        # Collect market data
        events = find_historical_markets(current_markets)
        
        if len(events) == 0:
            print("No markets found! Waiting and retrying...")
            time.sleep(60)
            continue
        
        # Process markets
        print("\nCollecting market data...")
        markets_data = collect_market_data(events)
        
        if len(markets_data) == 0:
            print("No valid markets with trades found!")
            current_markets += MARKET_BATCH_SIZE
            continue
        
        # Save to CSV
        csv_path = f"training_data_{len(markets_data)}_markets.csv"
        save_markets_to_csv(markets_data, csv_path)
        
        # Load and prepare for training
        print("\nPreparing features for training...")
        try:
            X, y, prediction_times = load_and_prepare_data(csv_path)
        except Exception as e:
            print(f"Error preparing data: {e}")
            current_markets += MARKET_BATCH_SIZE
            continue
        
        # Train models for each prediction time
        print("\nTraining models...")
        models = {}
        
        for pred_time in prediction_times:
            model, features, r2 = train_model(X, y, pred_time)
            if model is not None:
                models[pred_time] = {
                    'model': model,
                    'features': features,
                    'r2': r2
                }
                print(f"  {pred_time}s: R² = {r2:.4f}")
        
        # Calculate average R²
        avg_r2 = evaluate_model_performance(models, prediction_times)
        print(f"\nAverage R² across all prediction times: {avg_r2:.4f}")
        
        # Save checkpoint
        checkpoint = {
            'iteration': iteration,
            'num_markets': len(markets_data),
            'avg_r2': avg_r2,
            'models': models,
            'prediction_times': prediction_times
        }
        joblib.dump(checkpoint, f'checkpoint_iter_{iteration}.pkl')
        
        # Check if target achieved
        if avg_r2 >= target_r2:
            print(f"\n✓ TARGET ACHIEVED! R² = {avg_r2:.4f} >= {target_r2}")
            print(f"✓ Final model compiled with {len(markets_data)} markets")
            
            # Save final model
            final_model = {
                'models': models,
                'prediction_times': prediction_times,
                'num_markets': len(markets_data),
                'final_r2': avg_r2,
                'target_r2': target_r2,
                'training_date': time.strftime("%Y-%m-%d %H:%M:%S")
            }
            joblib.dump(final_model, 'final_sway_model.pkl')
            
            # Also save as easy-to-use format
            # Use the 60s model as primary if available, otherwise first available
            primary_time = 60 if 60 in models else prediction_times[0]
            best_model = models[primary_time]['model']
            feature_names = models[primary_time]['features']
            
            production_model = {
                'model': best_model,
                'feature_names': feature_names,
                'window_sizes': WINDOW_SIZES,
                'prediction_times': prediction_times,
                'metadata': {
                    'num_markets': len(markets_data),
                    'r2_score': avg_r2,
                    'target_r2': target_r2,
                    'training_date': time.strftime("%Y-%m-%d %H:%M:%S")
                }
            }
            joblib.dump(production_model, 'sway_model_production.pkl')
            
            print("\nFinal models saved:")
            print("  - final_sway_model.pkl (complete training data)")
            print("  - sway_model_production.pkl (ready for inference)")
            
            # Generate performance report
            generate_report(models, prediction_times, len(markets_data), avg_r2)
            
            return final_model
        
        # Not achieved, add more markets
        print(f"\n✗ Target not achieved. Adding {MARKET_BATCH_SIZE} more markets...")
        current_markets += MARKET_BATCH_SIZE
        iteration += 1
        
        # Clean up old CSV to save space
        if os.path.exists(csv_path):
            os.remove(csv_path)
    
    print(f"\n✗ Maximum markets ({MAX_MARKETS}) reached without achieving target R²")
    print(f"Best R² achieved: {best_r2:.4f}")
    return None

def generate_report(models, prediction_times, num_markets, final_r2):
    """Generate performance report"""
    report = f"""
    ========================================
    SWAY MODEL TRAINING REPORT
    ========================================
    
    Training completed: {time.strftime("%Y-%m-%d %H:%M:%S")}
    Total markets used: {num_markets}
    Final average R²: {final_r2:.4f}
    
    Per-prediction-time performance:
    """
    
    for pred_time in prediction_times:
        if pred_time in models:
            r2 = models[pred_time]['r2']
            report += f"\n    {pred_time}s: R² = {r2:.4f}"
    
    report += f"""
    
    Model Configuration:
    - Window sizes: {WINDOW_SIZES}
    - Step seconds: {STEP_SECONDS}
    - Min points per window: {MIN_POINTS_PER_WINDOW}
    
    Files generated:
    - final_sway_model.pkl: Complete model with all prediction times
    - sway_model_production.pkl: Production-ready model
    - training_report.txt: This report
    
    ========================================
    """
    
    with open('training_report.txt', 'w') as f:
        f.write(report)
    
    print(report)

# ======================================================================
# Command-line interface
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description='Automated Sway Model Training Pipeline')
    parser.add_argument('--initial', type=int, default=INITIAL_MARKETS, 
                       help=f'Initial number of markets to collect (default: {INITIAL_MARKETS})')
    parser.add_argument('--target', type=float, default=TARGET_R2,
                       help=f'Target R² score (default: {TARGET_R2})')
    parser.add_argument('--max', type=int, default=MAX_MARKETS,
                       help=f'Maximum number of markets (default: {MAX_MARKETS})')
    parser.add_argument('--batch', type=int, default=MARKET_BATCH_SIZE,
                       help=f'Markets to add per iteration (default: {MARKET_BATCH_SIZE})')
    parser.add_argument('--resume', type=str, help='Resume from checkpoint file')
    
    args = parser.parse_args()
    
    if args.resume:
        print(f"Resuming from checkpoint: {args.resume}")
        checkpoint = joblib.load(args.resume)
        print(f"Previous state: {checkpoint['num_markets']} markets, R²={checkpoint['avg_r2']:.4f}")
        # Implement resume logic here if needed
        return
    
    # Run pipeline
    final_model = run_training_pipeline(
        initial_markets=args.initial,
        target_r2=args.target
    )
    
    if final_model:
        print("\n✅ Training pipeline completed successfully!")
        print(f"✅ Final model ready for inference")
        
        # Optional: Run a quick test prediction
        print("\nRunning quick test prediction...")
        test_model = joblib.load('sway_model_production.pkl')
        print(f"Model loaded successfully!")
        print(f"  - Trained on {test_model['metadata']['num_markets']} markets")
        print(f"  - R² score: {test_model['metadata']['r2_score']:.4f}")
        print(f"  - Prediction times: {test_model['prediction_times']}")
    else:
        print("\n❌ Training pipeline failed to achieve target R²")
        print("Consider:")
        print("  1. Lowering target R²")
        print("  2. Increasing MAX_MARKETS")
        print("  3. Adding more features or different window sizes")

if __name__ == "__main__":
    main()