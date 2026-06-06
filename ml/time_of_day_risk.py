"""Polynomial-based Time-of-Day Risk Assessment Module"""

import json
from datetime import datetime
from pathlib import Path
from typing import Tuple

import numpy as np


def load_polynomial_coefficients(json_file: str) -> dict:
    """Load polynomial coefficients from risk_scores.json."""
    json_path = Path(json_file)
    if not json_path.exists():
        raise FileNotFoundError(f"Risk scores JSON file not found: {json_path}")
    
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        if 'polynomial_coefficients' not in data:
            raise ValueError("Invalid JSON: missing 'polynomial_coefficients' key")
        return data['polynomial_coefficients']
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")


def evaluate_polynomial(x: float, coefficients: list) -> float:
    """Evaluate polynomial: sum(coeff[i] * x^i)"""
    return sum(coeff * (x ** i) for i, coeff in enumerate(coefficients))


def normalize_risk_score(raw_score: float) -> float:
    """Clamp risk score to [0.0, 1.0]"""
    return float(np.clip(raw_score, 0.0, 1.0))


def get_risk_score_for_time(hour: int, minute: int, json_file: str) -> float:
    """Get risk score for a specific time using polynomial model."""
    if not (0 <= hour <= 23):
        raise ValueError(f"Hour must be 0-23, got {hour}")
    if not (0 <= minute <= 59):
        raise ValueError(f"Minute must be 0-59, got {minute}")
    
    poly_data = load_polynomial_coefficients(json_file)
    coefficients = poly_data['coefficients']
    
    # Normalize time to 0-1 range
    total_minutes = hour * 60 + minute
    x = total_minutes / (24 * 60)
    
    raw_score = evaluate_polynomial(x, coefficients)
    return normalize_risk_score(raw_score)


def get_current_risk_score(json_file: str) -> Tuple[str, float]:
    """Get risk score for current time."""
    now = datetime.now()
    score = get_risk_score_for_time(now.hour, now.minute, json_file)
    time_str = f"{now.hour:02d}:{now.minute:02d}"
    return time_str, score


def get_risk_score_for_five_minute_interval(interval: str, json_file: str) -> float:
    """Get risk score for a 5-minute interval (e.g., "20:30")."""
    try:
        parts = interval.split(':')
        if len(parts) != 2:
            raise ValueError()
        hour, minute = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        raise ValueError(f"Invalid interval format. Expected 'HH:MM', got '{interval}'")
    return get_risk_score_for_time(hour, minute, json_file)


def get_risk_scores_all_five_minute_intervals(json_file: str) -> dict[str, float]:
    """Get risk scores for all 5-minute intervals in a 24-hour day."""
    scores = {}
    for hour in range(24):
        for minute in range(0, 60, 5):
            interval = f"{hour:02d}:{minute:02d}"
            scores[interval] = get_risk_score_for_time(hour, minute, json_file)
    return scores


def get_riskiest_times(json_file: str, top_n: int = 10) -> list[Tuple[str, float]]:
    """Get the riskiest 5-minute intervals in the day."""
    scores = get_risk_scores_all_five_minute_intervals(json_file)
    return sorted(scores.items(), key=lambda x: x[1])[:top_n]


def get_safest_times(json_file: str, top_n: int = 10) -> list[Tuple[str, float]]:
    """Get the safest 5-minute intervals in the day."""
    scores = get_risk_scores_all_five_minute_intervals(json_file)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_n]


def get_average_risk_for_hour(hour: int, json_file: str) -> float:
    """Get average risk score for all 5-minute intervals in an hour."""
    if not (0 <= hour <= 23):
        raise ValueError(f"Hour must be 0-23, got {hour}")
    scores = [get_risk_score_for_time(hour, minute, json_file) for minute in range(0, 60, 5)]
    return float(np.mean(scores))


def get_average_risk_for_time_range(start_hour: int, end_hour: int, json_file: str) -> float:
    """Get average risk score for a range of hours."""
    if start_hour > end_hour:
        raise ValueError("start_hour must be <= end_hour")
    scores = [get_average_risk_for_hour(hour, json_file) for hour in range(start_hour, end_hour + 1)]
    return float(np.mean(scores))
