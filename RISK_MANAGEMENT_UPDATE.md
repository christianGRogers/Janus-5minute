# Risk Management Update: Per-Market Position Limits

## Overview
Added per-market risk capping to prevent concentration risk when placing multiple orders on the same market.

## Changes Made to `late_entry.go`

### 1. **New Data Structures**
- Added `marketExposure map[string]float64` to track total USDC cost basis per market
- Added `maxMarketExposure float64` field set to 0.30 (30% of balance)

### 2. **New Helper Function: `calculateSafePositionSize()`**
Calculates position size respecting BOTH constraints:
- **Per-trade limit**: `balance × RiskTolerance × percentOfMax`
  - RiskTolerance = 0.2 (20% of balance per trade)
  - percentOfMax varies by tier (0.25 for Tier 1, 0.35 for Tier 2, 1.0 for Extreme)
  
- **Per-market limit**: `balance × 0.30 - currentExposure`
  - 30% of balance is the absolute cap per market
  - Reduces as you add more positions to the same market

Returns:
- `maxPerTradeSize`: What 20% rule allows
- `remainingMarketCapacity`: Space left in 30% per-market cap
- `recommendedSize`: Min of above two (the constraint that's tighter)
- `isWithinCap`: Boolean indicating if safe to proceed

### 3. **Updated BUY Strategies**
All three BUY tiers now check per-market cap before placing orders:

**Extreme Confidence (0.98+)**
- Calls `calculateSafePositionSize(marketID, 1.0)`
- Rejects if would exceed 30% per-market cap
- Logs current/max/remaining exposure

**Tier 1 High Confidence (0.85-0.94)**
- Calls `calculateSafePositionSize(marketID, 0.25)`
- Conservative sizing (25% of 20% = 5% of balance per order max)
- Blocked if market already has 30%+ exposure

**Tier 2 Preferred High (0.95+)**
- Calls `calculateSafePositionSize(marketID, 0.35)`
- Standard sizing (35% of 20% = 7% of balance per order max)
- Blocked if market already has 30%+ exposure

### 4. **Market Exposure Tracking: `OnOrderPlaced()`**
- **BUY**: Adds `price × size` to `marketExposure[marketID]`
- **SELL**: Subtracts `price × size` from `marketExposure[marketID]`
- Prevents negative exposure values

### 5. **Reset on New Window: `OnMarketWindowChange()` and `Reset()`**
- Clears `marketExposure` map at start of each 5-minute window
- Prevents stale exposure values from affecting next window

## Risk Management Logic

### Example: $100 Balance

| Scenario | Exposure | Result |
|----------|----------|--------|
| **Order 1** (Tier 2) | $0 → $7 | ✓ Allowed (7% < 30%) |
| **Order 2** (Tier 2) | $7 → $14 | ✓ Allowed (14% < 30%) |
| **Order 3** (Tier 2) | $14 → $21 | ✓ Allowed (21% < 30%) |
| **Order 4** (Tier 2) | $21 → $28 | ✓ Allowed (28% < 30%) |
| **Order 5** (Tier 2) | $28 → $35 | ✗ Rejected (35% > 30%) |

### Example: $100 Balance with Price Changes

| Event | Action | Cost/Proceeds | Exposure | Status |
|-------|--------|---------------|----------|--------|
| Buy 50 @ $0.40 | BUY | -$20 | $20 | ✓ 20% |
| Redeem 50 @ $0.45 | SELL | +$22.50 | -$2.50 → $0 | ✓ Recovered |
| Buy 30 @ $0.50 | BUY | -$15 | $15 | ✓ 15% |
| Buy 20 @ $0.55 | BUY | -$11 | $26 | ✓ 26% |
| Buy 10 @ $0.50 | BUY | -$5 | $31 | ✗ >30%, REJECTED |

## Logging
All buy signals now log:
```
Market exposure: $X.XX/$Y.YY (current/max allowed)
```

Example:
```
BUY TIER 2 ... size: 20 shares ($10.00), market exposure: $27.50/$30.00
```

## Testing Recommendations
1. Place multiple orders on same market - verify 4th order gets rejected when approaching 30% cap
2. Check logs for "Would exceed 30% per-market cap" message
3. Verify `marketExposure` resets when new 5-minute window begins
4. Test with various balance levels (affects per-market cap in absolute terms)

## Benefits
- ✅ **Prevents concentration**: No single market can exceed 30% of balance
- ✅ **Allows stacking**: 3-4 small orders on same market still possible
- ✅ **Dynamic**: Works with any account size
- ✅ **Self-healing**: SELL orders automatically reduce exposure
- ✅ **Visible**: All exposure logged for monitoring
