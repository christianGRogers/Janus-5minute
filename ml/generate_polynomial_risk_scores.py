#!/usr/bin/env python3
"""
Generate polynomial risk scores and save to risk_scores.json.

This script:
1. Loads trading data from market_export.csv files
2. Trains a polynomial model to fit risk patterns across the 24-hour day
3. Generates both polynomial coefficients and pre-computed 5-minute scores
4. Saves everything to config/risk_scores.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime
import numpy as np
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import Ridge

# Add ml directory to path
sys.path.insert(0, str(Path(__file__).parent))
from time_of_day_risk import TimeOfDayRiskAssessment, initialize_from_workspace


def generate_polynomial_risk_scores(workspace_root: str, output_file: str, polynomial_degree: int = 6):
    """
    Generate polynomial risk scores and save to JSON file.
    
    Args:
        workspace_root: Root directory of the workspace
        output_file: Path where to save the risk_scores.json file
        polynomial_degree: Degree of polynomial to fit (default 6)
    """
    print("=" * 80)
    print("GENERATING POLYNOMIAL RISK SCORES")
    print("=" * 80)
    
    # Initialize and train the model
    print(f"\nTraining model on workspace: {workspace_root}")
    model = initialize_from_workspace(workspace_root)
    
    # Get all 5-minute interval scores
    print("\nGenerating risk scores for all 5-minute intervals...")
    five_min_scores = model.get_risk_scores_all_five_minute_intervals()
    print(f"Generated {len(five_min_scores)} 5-minute interval scores")
    
    # Prepare data for polynomial fitting
    # Create training data: (time_normalized, risk_score) pairs
    X_data = []
    y_data = []
    
    for hour in range(24):
        for minute in range(0, 60, 5):
            interval_key = f"{hour:02d}:{minute:02d}"
            if interval_key in five_min_scores:
                # Normalize time to [0, 1]: (hour*60 + minute) / (24*60)
                time_normalized = (hour * 60 + minute) / (24.0 * 60.0)
                X_data.append([time_normalized])
                y_data.append(five_min_scores[interval_key])
    
    X_data = np.array(X_data)
    y_data = np.array(y_data)
    
    print(f"\nFitting polynomial of degree {polynomial_degree}...")
    print(f"Training data: {len(X_data)} samples")
    
    # Fit polynomial
    poly_features = PolynomialFeatures(degree=polynomial_degree, include_bias=True)
    X_poly = poly_features.fit_transform(X_data)
    
    # Use Ridge regression for stability
    model_poly = Ridge(alpha=1.0)
    model_poly.fit(X_poly, y_data)
    
    # Extract coefficients (first one is bias/constant term)
    coefficients = model_poly.coef_.tolist()
    coefficients.insert(0, model_poly.intercept_)  # Add intercept as first coefficient
    
    print(f"Polynomial coefficients: {[f'{c:.4f}' for c in coefficients]}")
    
    # Evaluate fit quality
    y_pred = model_poly.predict(X_poly)
    mse = np.mean((y_data - y_pred) ** 2)
    rmse = np.sqrt(mse)
    r2 = 1 - (np.sum((y_data - y_pred) ** 2) / np.sum((y_data - np.mean(y_data)) ** 2))
    
    print(f"\nPolynomial Fit Quality:")
    print(f"  RMSE: {rmse:.6f}")
    print(f"  R²: {r2:.6f}")
    
    # Create output data structure
    output_data = {
        "generated_at": str(datetime.now().isoformat()),
        "model_type": "TimeOfDayRiskAssessment_polynomial",
        "scale": "0=riskiest, 1=safest",
        "description": f"Risk scores computed using degree-{polynomial_degree} polynomial: risk = sum(coeff[i] * x^i) where x is (hour*60+minute)/(24*60)",
        "polynomial_coefficients": {
            "degree": polynomial_degree,
            "coefficients": coefficients,
            "fit_quality": {
                "rmse": float(rmse),
                "r_squared": float(r2),
                "training_samples": len(X_data)
            }
        },
        "five_minute_intervals": five_min_scores,
        "training_stats": {
            "total_trades": len(model.five_minute_stats),
            "five_minute_intervals_analyzed": len(five_min_scores),
        }
    }
    
    # Save to JSON file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\n✓ Risk scores saved to: {output_path}")
    print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"  - Polynomial degree: {polynomial_degree}")
    print(f"  - Coefficients: {len(coefficients)}")
    print(f"  - 5-minute intervals: {len(five_min_scores)}")
    
    return output_data


if __name__ == "__main__":
    # Get workspace root from command line or use default
    if len(sys.argv) > 1:
        workspace_root = sys.argv[1]
    else:
        workspace_root = str(Path(__file__).parent.parent)
    
    # Output file
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
    else:
        output_file = str(Path(workspace_root) / "config" / "risk_scores.json")
    
    # Polynomial degree
    polynomial_degree = 6
    if len(sys.argv) > 3:
        try:
            polynomial_degree = int(sys.argv[3])
        except ValueError:
            print(f"Warning: Invalid polynomial degree '{sys.argv[3]}', using default {polynomial_degree}")
    
    try:
        generate_polynomial_risk_scores(workspace_root, output_file, polynomial_degree)
        print("\n" + "=" * 80)
        print("SUCCESS: Polynomial risk scores generated and saved!")
        print("=" * 80)
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
