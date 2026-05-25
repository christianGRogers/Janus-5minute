"""
Example usage of the Time-of-Day Risk Assessment module.

This demonstrates how to:
1. Train the model on historical trading data
2. Get risk scores for specific hours
3. Find the riskiest and safest trading times
4. Use the risk score in trading logic
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.time_of_day_risk import (
    initialize_from_workspace,
    initialize_risk_model,
    TimeOfDayRiskAssessment,
)


def example_basic_usage():
    """Basic example of training and using the risk model."""
    print("=" * 60)
    print("BASIC USAGE EXAMPLE")
    print("=" * 60)

    # Auto-discover CSV files in the workspace (parent of ml folder)
    workspace_root = Path(__file__).parent.parent
    risk_model = initialize_from_workspace(str(workspace_root))

    print("\n[OK] Model trained successfully!")
    print(f"  Total trades analyzed: {risk_model.hourly_stats[0]}")

    # Get risk for a specific hour (e.g., 2 PM)
    hour_14 = 14  # 2 PM in 24-hour format
    risk_score = risk_model.get_risk_score(hour_14)
    print(f"\nRisk score for 2:00 PM (hour 14): {risk_score:.3f}")
    print(f"  (0 = riskiest, 1 = safest)")


def example_find_best_times():
    """Find the safest and riskiest times to trade."""
    print("\n" + "=" * 60)
    print("FIND BEST/WORST TRADING TIMES")
    print("=" * 60)

    workspace_root = Path(__file__).parent.parent
    risk_model = initialize_from_workspace(str(workspace_root))

    # Get safest hours
    safest = risk_model.get_safest_hours(top_n=5)
    print("\n[GREEN] SAFEST HOURS TO TRADE:")
    for hour, score in safest:
        hour_str = f"{hour:02d}:00" if hour < 24 else "Invalid"
        am_pm = "AM" if hour < 12 else "PM"
        display_hour = hour if hour <= 12 else hour - 12
        if hour == 0:
            display_hour = 12
            am_pm = "AM"
        print(f"  {display_hour:2d}:00 {am_pm}  ->  Risk Score: {score:.3f}")

    # Get riskiest hours
    riskiest = risk_model.get_riskiest_hours(top_n=5)
    print("\n[RED] RISKIEST HOURS TO TRADE:")
    for hour, score in riskiest:
        hour_str = f"{hour:02d}:00"
        am_pm = "AM" if hour < 12 else "PM"
        display_hour = hour if hour <= 12 else hour - 12
        if hour == 0:
            display_hour = 12
            am_pm = "AM"
        print(f"  {display_hour:2d}:00 {am_pm}  ->  Risk Score: {score:.3f}")


def example_trading_logic():
    """Example of using risk scores in trading logic."""
    print("\n" + "=" * 60)
    print("USING RISK SCORES IN TRADING LOGIC")
    print("=" * 60)

    workspace_root = Path(__file__).parent.parent
    risk_model = initialize_from_workspace(str(workspace_root))

    # Example: Different position sizes based on risk
    def calculate_position_size(hour: int, base_size: float = 1.0) -> float:
        """
        Calculate position size based on time-of-day risk.
        
        Args:
            hour: Hour in 24-hour format
            base_size: Base position size (default 1.0 = 100%)
            
        Returns:
            Adjusted position size
        """
        risk_score = risk_model.get_risk_score(hour)
        
        # Adjust position based on risk:
        # - At risk_score 1.0 (safest): full position
        # - At risk_score 0.0 (riskiest): 50% position
        adjusted_size = base_size * (0.5 + 0.5 * risk_score)
        return adjusted_size

    # Test different hours
    test_hours = [9, 12, 14, 18, 22]
    print("\nPosition Sizing by Hour (base_size=1.0):")
    print("Hour  | Risk Score | Position Size")
    print("------|------------|---------------")

    for hour in test_hours:
        risk = risk_model.get_risk_score(hour)
        position = calculate_position_size(hour, base_size=1.0)
        am_pm = "AM" if hour < 12 else "PM"
        display_hour = hour if hour <= 12 else hour - 12
        if hour == 0:
            display_hour = 12
            am_pm = "AM"
        print(f"{display_hour:2d}:00 {am_pm} | {risk:.3f}      | {position:.3f}")


def example_time_range():
    """Example of analyzing risk for time ranges."""
    print("\n" + "=" * 60)
    print("ANALYZE RISK BY TIME RANGE")
    print("=" * 60)

    workspace_root = Path(__file__).parent.parent
    risk_model = initialize_from_workspace(str(workspace_root))

    # Trading hours: 9 AM to 5 PM
    morning_risk = risk_model.get_risk_by_time_range(9, 12)
    afternoon_risk = risk_model.get_risk_by_time_range(13, 17)
    evening_risk = risk_model.get_risk_by_time_range(17, 21)
    night_risk = risk_model.get_risk_by_time_range(21, 23)

    print("\nAverage Risk Scores by Time Range:")
    print(f"  Morning    (9 AM - 12 PM):  {morning_risk:.3f}")
    print(f"  Afternoon (1 PM - 5 PM):   {afternoon_risk:.3f}")
    print(f"  Evening    (5 PM - 9 PM):   {evening_risk:.3f}")
    print(f"  Night      (9 PM - 11 PM):  {night_risk:.3f}")

    # Determine best time
    ranges = {
        "Morning": morning_risk,
        "Afternoon": afternoon_risk,
        "Evening": evening_risk,
        "Night": night_risk
    }
    best_time = max(ranges, key=ranges.get)
    print(f"\n[OK] Best trading time: {best_time}")


def example_all_hours():
    """Show risk scores for all 24 hours."""
    print("\n" + "=" * 60)
    print("RISK SCORES FOR ALL 24 HOURS")
    print("=" * 60)

    workspace_root = Path(__file__).parent.parent
    risk_model = initialize_from_workspace(str(workspace_root))

    scores = risk_model.get_risk_scores_all_hours()

    print("\nHour | Risk Score | Safety Level")
    print("-----|------------|-------------------")

    for hour in range(24):
        score = scores[hour]
        
        # Create a visual bar
        bar_length = int(score * 20)
        bar = "=" * bar_length + "-" * (20 - bar_length)
        
        # Determine safety level
        if score >= 0.7:
            safety = "[GREEN] Very Safe"
        elif score >= 0.5:
            safety = "[YELLOW] Moderate"
        elif score >= 0.3:
            safety = "[ORANGE] Risky"
        else:
            safety = "[RED] Very Risky"

        am_pm = "AM" if hour < 12 else "PM"
        display_hour = hour if hour <= 12 else hour - 12
        if hour == 0:
            display_hour = 12
            am_pm = "AM"

        print(f"{display_hour:2d}:00 {am_pm} | {score:.3f}     | {bar} {safety}")


if __name__ == "__main__":
    try:
        # Run all examples
        example_basic_usage()
        example_find_best_times()
        example_trading_logic()
        example_time_range()
        example_all_hours()

        print("\n" + "=" * 60)
        print("[OK] All examples completed successfully!")
        print("=" * 60)

    except ImportError as e:
        print(f"Error: Missing required package: {e}")
        print("\nPlease install required packages:")
        print("  pip install scikit-learn pandas numpy")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
