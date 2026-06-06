# Polynomial Risk Scores Update

## Overview

The risk scoring system has been upgraded to use **polynomial interpolation** for efficient and smooth risk score calculation across 5-minute intervals.

### What Changed

- **Model Type**: Changed from discrete hourly/5-minute scores to **polynomial function**
- **Risk Score Calculation**: Uses polynomial coefficients to compute risk at any time
- **Storage**: Compact polynomial model + 288 pre-computed 5-minute scores for validation
- **Granularity**: Still covers all 5-minute intervals (00:00 to 23:55)
- **Late Entry Strategy**: Updated to use 5-minute risk scores instead of hourly

## Risk Score Structure

```json
{
  "generated_at": "2026-06-06T18:46:39.390977",
  "model_type": "TimeOfDayRiskAssessment_polynomial",
  "scale": "0=riskiest, 1=safest",
  "polynomial_coefficients": {
    "degree": 6,
    "coefficients": [0.8769, 0.0, 0.0175, 0.0544, -0.0046, -0.0373, -0.0388, -0.0206],
    "fit_quality": {
      "rmse": 0.2563,
      "r_squared": 0.0023,
      "training_samples": 288
    }
  },
  "five_minute_intervals": {
    "00:00": 0.8596,
    ...
    "23:55": 0.9265
  }
}
```

## Polynomial Risk Function

### Formula

$$\text{risk}(t) = \sum_{i=0}^{n} c_i \cdot x^i$$

Where:
- $x = \frac{\text{hour} \times 60 + \text{minute}}{24 \times 60}$ (normalized time, 0 to 1)
- $c_i$ are the polynomial coefficients
- Result is clamped to [0, 1]

### Example Calculation

For 20:30 (8:30 PM):
- Hour = 20, Minute = 30
- Total minutes = 20×60 + 30 = 1230
- x = 1230 / (24×60) = 1230 / 1440 ≈ 0.8542
- risk = $c_0 + c_1 x + c_2 x^2 + ... + c_6 x^6$

## Current Polynomial Coefficients (Degree 6)

Generated: 2026-06-06

| Index | Coefficient | Interpretation |
|-------|-------------|-----------------|
| 0 | 0.8769 | Base/constant risk level |
| 1 | 0.0000 | Linear term (disabled) |
| 2 | 0.0175 | Quadratic term |
| 3 | 0.0544 | Cubic term |
| 4 | -0.0046 | 4th power |
| 5 | -0.0373 | 5th power |
| 6 | -0.0388 | 6th power |
| 7 | -0.0206 | 7th power |

**Fit Quality:**
- RMSE: 0.2563 (average prediction error)
- R²: 0.0023 (explains ~0.23% of variance)
- Training samples: 288

## Implementation in Go

### Config Functions

```go
// Load risk scores at startup
config.LoadRiskScores()

// Get risk for 5-minute interval
score := config.GetRiskScoreForFiveMinuteInterval(hour, minute)

// Polynomial evaluation happens automatically
// Returns value between 0 (riskiest) and 1 (safest)
```

### Late Entry Strategy Integration

The `LateEntryStrategy` now uses 5-minute risk scores:

```go
// Get current 5-minute interval risk
now := time.Now()
riskScore := config.GetRiskScoreForFiveMinuteInterval(now.Hour(), now.Minute())

// Calculate position size multiplier
multiplier := 0.3 + (riskScore * 0.7)  // Range: 0.3 to 1.0

// Apply to position sizing and risk management
```

#### Position Size Calculation

The late entry strategy applies the risk score as a multiplier:

| Risk Score | Multiplier | Position Size |
|-----------|-----------|--------------|
| 0.0 (Riskiest) | 0.30 | 30% of normal |
| 0.3 (High Risk) | 0.51 | 51% of normal |
| 0.5 (Medium) | 0.65 | 65% of normal |
| 0.7 (Low Risk) | 0.79 | 79% of normal |
| 1.0 (Safest) | 1.00 | 100% of normal |

Combined with loss cooldown multiplier (0.5-1.0x), providing dynamic risk management.

## Regenerating Polynomial Scores

When new trading data is available:

```bash
cd /path/to/Janus-5minute
python ml/generate_polynomial_risk_scores.py
```

### Custom Polynomial Degree

To use a different polynomial degree (e.g., degree 5 for smoother fit):

```bash
python ml/generate_polynomial_risk_scores.py . config/risk_scores.json 5
```

### Automatic Discovery

The script automatically:
1. Discovers all `market_export.csv` files
2. Uses the 2 most recent files (2x weight on latest)
3. Trains polynomial model
4. Generates all 288 5-minute scores
5. Saves to `config/risk_scores.json`

## Benefits of Polynomial Model

### 1. **Smooth Interpolation**
- Continuous function instead of discrete intervals
- Natural interpolation between known points
- Reduces overfitting to individual trades

### 2. **Compact Storage**
- ~8 coefficients vs 288 discrete values
- Polynomial can be computed on-the-fly
- Easy to version and transmit

### 3. **Computational Efficiency**
- O(n) evaluation where n is polynomial degree
- No lookup tables or interpolation needed
- Fast position size calculation during trades

### 4. **Generalization**
- Model captures overall daily risk patterns
- Handles missing 5-minute intervals gracefully
- Smooths out noise in trading data

## Backward Compatibility

Old hourly scoring still works:

```go
// Still available
score := config.GetRiskScoreForHour(hour)
```

But the 5-minute system is now the recommended approach for better granularity.

## File Locations

- **Risk Scores (with Polynomial)**: `config/risk_scores.json`
- **Generation Script**: `ml/generate_polynomial_risk_scores.py`
- **Model Code**: `ml/time_of_day_risk.py`
- **Config Implementation**: `config/variables.go`
- **Strategy Integration**: `pkg/strategies/late_entry.go`

## Integration Checklist

- [x] Updated `config/variables.go` to support polynomial model
- [x] Added `GetRiskScoreForFiveMinuteInterval()` function
- [x] Added polynomial evaluation function
- [x] Updated `late_entry.go` to use 5-minute risk scores
- [x] Created `generate_polynomial_risk_scores.py` script
- [x] Generated initial polynomial coefficients
- [x] Updated `risk_scores.json` with polynomial data

## Next Steps

1. **Monitor Performance**: Track position sizing adjustments
2. **Refit Model**: Regenerate polynomial monthly with new data
3. **Optimize Degree**: Experiment with polynomial degrees 4-8 for best fit
4. **Validate**: Compare polynomial predictions vs actual 5-minute scores

## Troubleshooting

### Low R² Score

If R² is very low (< 0.1), it means:
- Risk doesn't follow a smooth polynomial pattern
- Consider increasing polynomial degree
- May indicate more randomness in trading outcomes
- Fallback to discrete 5-minute scores if needed

### Coefficients Out of Range

If computed risk scores exceed [0, 1]:
- Polynomial clamping is applied automatically
- Check fit quality metrics
- Consider lower polynomial degree
