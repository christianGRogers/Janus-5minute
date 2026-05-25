"""
Export risk scores to a static JSON file for use by trading bots.

This script trains the ML model and exports the 24-hour risk scores
to a static file that can be loaded by Go services at startup.
"""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from ml.time_of_day_risk import initialize_from_workspace


def export_risk_scores():
    """Train model and export risk scores to JSON."""
    print("[Export] Initializing risk model from workspace...")
    
    # Initialize and train the model
    risk_model = initialize_from_workspace(".")
    
    if not risk_model.is_trained:
        print("[Export] ERROR: Model failed to train!")
        return False
    
    print("[Export] Model trained successfully!")
    
    # Get risk scores for all 24 hours
    all_scores = risk_model.get_risk_scores_all_hours()
    
    # Build output dictionary with hour:score mapping
    risk_scores_data = {
        "generated_at": str(Path.cwd()),
        "model_type": "TimeOfDayRiskAssessment",
        "scale": "0=riskiest, 1=safest",
        "hours": {}
    }
    
    for hour in range(24):
        score = all_scores.get(hour, 0.5)
        risk_scores_data["hours"][str(hour)] = round(score, 4)
    
    # Write to JSON file
    output_path = Path("config/risk_scores.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(risk_scores_data, f, indent=2)
    
    print(f"[Export] Risk scores exported to {output_path}")
    
    # Print summary
    safest = risk_model.get_safest_hours(5)
    riskiest = risk_model.get_riskiest_hours(5)
    
    print("\n[Export] SAFEST HOURS (highest risk scores):")
    for hour, score in safest:
        print(f"  Hour {hour:2d}: {score:.4f}")
    
    print("\n[Export] RISKIEST HOURS (lowest risk scores):")
    for hour, score in riskiest:
        print(f"  Hour {hour:2d}: {score:.4f}")
    
    return True


if __name__ == "__main__":
    success = export_risk_scores()
    exit(0 if success else 1)
