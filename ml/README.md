# ML Module - Time-of-Day Risk Assessment

This folder contains machine learning tools for analyzing and predicting trading risk based on time of day.

## Contents

- **`time_of_day_risk.py`** - Core ML module with the `TimeOfDayRiskAssessment` class
- **`examples.py`** - Complete working examples and usage patterns
- **`requirements.txt`** - Python dependencies
- **`README.md`** - Detailed documentation

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Basic Usage

```python
from ml.time_of_day_risk import initialize_from_workspace

# Train model on all market_export.csv files
risk_model = initialize_from_workspace(".")

# Get risk score for 2 PM (0 = riskiest, 1 = safest)
risk = risk_model.get_risk_score(14)
print(f"Risk at 2 PM: {risk:.3f}")
```

### 3. Run Examples

```bash
python ml/examples.py
```

## Risk Scoring

**Risk Score: 0-1 scale**
- **0** = Riskiest time to trade (historically poor outcomes)
- **1** = Safest time to trade (historically good outcomes)

The model uses Random Forest regression trained on:
- Win rates by hour
- Volatility patterns
- Trade outcomes
- Market behavior

## Key Functions

### Get Risk for Specific Hour
```python
score = risk_model.get_risk_score(14)  # 0.754
```

### Find Best Trading Times
```python
safest = risk_model.get_safest_hours(top_n=5)
riskiest = risk_model.get_riskiest_hours(top_n=5)
```

### Analyze Time Ranges
```python
morning_risk = risk_model.get_risk_by_time_range(9, 12)
afternoon_risk = risk_model.get_risk_by_time_range(13, 17)
```

### Get All Hour Scores
```python
all_scores = risk_model.get_risk_scores_all_hours()
# Returns: {0: 0.45, 1: 0.32, ..., 23: 0.67}
```

## Integration Example

```python
from ml.time_of_day_risk import initialize_from_workspace
from datetime import datetime

# Setup
risk_model = initialize_from_workspace(".")

# In trading logic
current_hour = datetime.now().hour
risk_score = risk_model.get_risk_score(current_hour)

# Adjust position size based on risk
position_size = base_size * (0.5 + 0.5 * risk_score)

# Skip trading if too risky
if risk_score < 0.3:
    print("Risk too high, skipping trade")
    return
```

## More Information

See `README.md` (one level up) for comprehensive documentation on:
- Feature importance
- Model performance metrics
- Trading strategy examples
- Troubleshooting
- Advanced usage

## Dependencies

- **scikit-learn** - Machine learning models
- **pandas** - Data processing
- **numpy** - Numerical computing
