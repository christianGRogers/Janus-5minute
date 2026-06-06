#!/usr/bin/env python3
"""
Example usage of polynomial risk scores.

Demonstrates how to:
1. Load polynomial coefficients from JSON
2. Evaluate polynomial at any time
3. Compare polynomial vs pre-computed scores
4. Visualize risk patterns
"""

import json
import numpy as np
from pathlib import Path


def load_risk_scores_json(json_file: str) -> dict:
    """Load risk scores from JSON file."""
    with open(json_file, 'r') as f:
        return json.load(f)


def evaluate_polynomial_risk(hour: int, minute: int, coefficients: list) -> float:
    """
    Evaluate polynomial risk function at given time.
    
    Args:
        hour: Hour (0-23)
        minute: Minute (0-59)
        coefficients: List of polynomial coefficients
        
    Returns:
        Risk score (0-1)
    """
    # Normalize time to [0, 1]
    x = (hour * 60 + minute) / (24.0 * 60.0)
    
    # Evaluate polynomial: sum(coeff[i] * x^i)
    result = 0.0
    for i, coeff in enumerate(coefficients):
        result += coeff * (x ** i)
    
    # Clamp to [0, 1]
    return max(0.0, min(1.0, result))


def main():
    """Run polynomial risk score examples."""
    json_file = "config/risk_scores.json"
    
    print("=" * 80)
    print("POLYNOMIAL RISK SCORES - EXAMPLES")
    print("=" * 80)
    
    # Load data
    print(f"\nLoading risk scores from: {json_file}")
    data = load_risk_scores_json(json_file)
    
    poly_model = data['polynomial_coefficients']
    coefficients = poly_model['coefficients']
    five_min_scores = data['five_minute_intervals']
    
    print(f"✓ Loaded polynomial (degree {poly_model['degree']})")
    print(f"✓ Fit quality: RMSE={poly_model['fit_quality']['rmse']:.4f}, R²={poly_model['fit_quality']['r_squared']:.4f}")
    
    # Example 1: Evaluate at specific times
    print("\n" + "=" * 80)
    print("[Example 1] Polynomial Evaluation at Specific Times")
    print("=" * 80)
    
    test_times = [
        (0, 0, "Midnight"),
        (6, 0, "6:00 AM"),
        (12, 0, "Noon"),
        (18, 0, "6:00 PM"),
        (20, 30, "8:30 PM"),
        (23, 55, "11:55 PM"),
    ]
    
    for hour, minute, label in test_times:
        poly_score = evaluate_polynomial_risk(hour, minute, coefficients)
        interval_key = f"{hour:02d}:{minute:02d}"
        actual_score = five_min_scores.get(interval_key, None)
        
        match = f"✓ {actual_score:.4f}" if actual_score else "N/A"
        diff = abs(poly_score - actual_score) if actual_score else None
        diff_str = f"(error: {diff:.4f})" if diff else ""
        
        risk_level = "🔴 HIGH" if poly_score < 0.3 else "🟡 MED" if poly_score < 0.7 else "🟢 LOW"
        
        print(f"{label:12} {hour:02d}:{minute:02d} | Poly: {poly_score:.4f} | Actual: {match} {diff_str} | {risk_level}")
    
    # Example 2: Hourly comparison
    print("\n" + "=" * 80)
    print("[Example 2] Hourly Average Risk Scores")
    print("=" * 80)
    
    print("Hour | Polynomial | Avg Actual | Diff  | Risk Level")
    print("-----|------------|------------|-------|------------")
    
    for hour in range(24):
        # Polynomial at top of hour
        poly_score = evaluate_polynomial_risk(hour, 0, coefficients)
        
        # Average of all 5-minute intervals in this hour
        intervals = [f"{hour:02d}:{minute:02d}" for minute in range(0, 60, 5)]
        actual_scores = [five_min_scores[interval] for interval in intervals]
        actual_avg = sum(actual_scores) / len(actual_scores)
        
        diff = abs(poly_score - actual_avg)
        risk_level = "HIGH" if poly_score < 0.3 else "MED" if poly_score < 0.7 else "LOW"
        
        print(f"{hour:02d}:00 | {poly_score:0.4f}      | {actual_avg:0.4f}      | {diff:0.4f} | {risk_level}")
    
    # Example 3: Find extremes
    print("\n" + "=" * 80)
    print("[Example 3] Extreme Risk Times (Polynomial Model)")
    print("=" * 80)
    
    all_scores = []
    for hour in range(24):
        for minute in range(0, 60, 5):
            score = evaluate_polynomial_risk(hour, minute, coefficients)
            all_scores.append((f"{hour:02d}:{minute:02d}", score))
    
    # Riskiest
    riskiest = sorted(all_scores, key=lambda x: x[1])[:5]
    print("\nRiskiest 5 times (lowest scores):")
    for interval, score in riskiest:
        print(f"  {interval}: {score:.4f} 🔴")
    
    # Safest
    safest = sorted(all_scores, key=lambda x: x[1], reverse=True)[:5]
    print("\nSafest 5 times (highest scores):")
    for interval, score in safest:
        print(f"  {interval}: {score:.4f} 🟢")
    
    # Example 4: Position sizing
    print("\n" + "=" * 80)
    print("[Example 4] Dynamic Position Sizing Based on Risk")
    print("=" * 80)
    
    def calculate_multiplier(risk_score: float) -> float:
        """Convert risk score to position size multiplier."""
        return 0.3 + (risk_score * 0.7)  # Range: 0.3 to 1.0
    
    print("\nPosition size multiplier by time (base = 1.0):")
    print("Time    | Risk Score | Multiplier | Position Size")
    print("--------|------------|------------|---------------")
    
    for hour in [0, 6, 12, 18, 23]:
        risk_score = evaluate_polynomial_risk(hour, 0, coefficients)
        multiplier = calculate_multiplier(risk_score)
        position_base = 1000.0  # Example: $1000 base position
        position_size = position_base * multiplier
        
        print(f"{hour:02d}:00  | {risk_score:0.4f}     | {multiplier:0.2f}x      | ${position_size:0.2f}")
    
    # Example 5: Validation
    print("\n" + "=" * 80)
    print("[Example 5] Polynomial vs Actual Scores - Error Analysis")
    print("=" * 80)
    
    errors = []
    for interval, actual_score in five_min_scores.items():
        hour, minute = map(int, interval.split(':'))
        poly_score = evaluate_polynomial_risk(hour, minute, coefficients)
        error = abs(poly_score - actual_score)
        errors.append(error)
    
    errors = np.array(errors)
    
    print(f"\nError Statistics:")
    print(f"  Mean absolute error: {np.mean(errors):.4f}")
    print(f"  Std dev: {np.std(errors):.4f}")
    print(f"  Min error: {np.min(errors):.4f}")
    print(f"  Max error: {np.max(errors):.4f}")
    print(f"  Median error: {np.median(errors):.4f}")
    
    percentiles = [25, 50, 75, 90, 95, 99]
    print(f"\nError Percentiles:")
    for p in percentiles:
        value = np.percentile(errors, p)
        print(f"  {p:3d}th percentile: {value:.4f}")
    
    print("\n" + "=" * 80)
    print("Examples completed!")
    print("=" * 80)


if __name__ == "__main__":
    main()
