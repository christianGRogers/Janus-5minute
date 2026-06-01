"""
Time-of-Day Risk Assessment Module

Uses machine learning to calculate trading risk based on time of day.
Risk score ranges from 0 (riskiest time) to 1 (safest time).

The model trains on historical trading data to identify patterns in:
- Win rate by hour
- Volatility by hour
- Trade outcome distribution
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression


class TimeOfDayRiskAssessment:
    """
    ML-based risk assessment tool for trading by time of day.
    
    Risk is calculated as a score from 0-1 where:
    - 0 = Riskiest time to trade
    - 1 = Safest time to trade
    """

    def __init__(self):
        """Initialize the risk assessment model."""
        self.model = RandomForestRegressor(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            n_jobs=-1
        )
        self.scaler = StandardScaler()
        self.hourly_stats = {}
        self.is_trained = False

    def _extract_hour_from_market_name(self, market_name: str) -> Optional[int]:
        """
        Extract hour from market name string.
        
        Expected format: "Bitcoin Up or Down - May 22, 8:30PM-8:35PM ET"
        
        Args:
            market_name: The market name from trading data
            
        Returns:
            Hour in 24-hour format (0-23), or None if parsing fails
        """
        # Extract time pattern like "8:30PM" or "10:15AM"
        pattern = r'(\d{1,2}):(\d{2})(AM|PM)'
        match = re.search(pattern, market_name)

        if not match:
            return None

        hour = int(match.group(1))
        period = match.group(3)

        # Convert to 24-hour format
        if period == 'PM' and hour != 12:
            hour += 12
        elif period == 'AM' and hour == 12:
            hour = 0

        return hour

    def _calculate_trade_outcome(self, row: pd.Series, all_trades: pd.DataFrame) -> float:
        """
        Identify if a Buy order was matched with a Redeem (win) or left open (loss).
        
        Logic:
        - Buy order WITH matching Redeem = 1.0 (WIN - position closed)
        - Buy order WITHOUT matching Redeem = 0.0 (LOSS - unmatched position)
        - Redeem order = skip (not counted)
        
        Matching logic: 
        - Each Buy needs a corresponding Redeem for the same market
        - Since multiple Buys can aggregate into one Redeem (batch redemption),
          we accumulate all Buys before a Redeem and check if they sum to the Redeem
        - Also allow direct 1:1 matches for single Buy → Redeem
        
        Args:
            row: CSV row with trade data
            all_trades: DataFrame with all trades for matching
            
        Returns:
            1.0 = win (matched Buy), 0.0 = loss (unmatched Buy), NaN = skip
        """
        action = row['action']

        if action == 'Redeem':
            return np.nan  # Skip Redeem orders

        if action != 'Buy':
            return np.nan

        try:
            # Get trade parameters
            market_name = str(row['marketName'])
            usdc_amount = float(row['usdcAmount'])
            row_index = row.name  # Get the index of this row in the DataFrame
            
            # Strategy 1: Look for a direct Redeem match (1:1 case)
            # Same market, same USDC amount (within 10% tolerance for floating point)
            tolerance = usdc_amount * 0.10  # 10% tolerance for direct match
            
            direct_match = all_trades[
                (all_trades['action'] == 'Redeem') &
                (all_trades['marketName'] == market_name) &
                (all_trades['usdcAmount'].astype(float).between(
                    usdc_amount - tolerance, 
                    usdc_amount + tolerance
                ))
            ]
            
            if len(direct_match) > 0:
                return 1.0  # Direct match found
            
            # Strategy 2: Look for an aggregated Redeem
            # This Buy might be part of a batch that was redeemed together
            # Get all Buys for this market that came before any Redeem
            market_trades = all_trades[all_trades['marketName'] == market_name].copy()
            
            if len(market_trades) == 0:
                return 0.0  # No matching market data at all
            
            # Find Redeems for this market
            redeems = market_trades[market_trades['action'] == 'Redeem'].copy()
            buys = market_trades[market_trades['action'] == 'Buy'].copy()
            
            if len(redeems) == 0:
                return 0.0  # No Redeems found - unmatched
            
            # For each Redeem, calculate if it covers this Buy order
            # by checking if there are enough accumulated Buys that sum close to the Redeem
            for redeem_idx, redeem_row in redeems.iterrows():
                redeem_amount = float(redeem_row['usdcAmount'])
                
                # Get all Buys up to this Redeem (by index)
                potential_buys = buys[buys.index <= row_index]
                
                if len(potential_buys) == 0:
                    continue
                
                # Sum the USDC amounts of accumulated Buys
                accumulated_usdc = potential_buys['usdcAmount'].astype(float).sum()
                
                # Check if this accumulated total matches the Redeem (within 5% tolerance)
                redeem_tolerance = redeem_amount * 0.05
                if abs(accumulated_usdc - redeem_amount) <= redeem_tolerance:
                    # This Buy is part of the batch that was redeemed!
                    return 1.0
            
            # No matching strategy worked
            return 0.0
                
        except (ValueError, KeyError, TypeError) as e:
            # On error, assume loss
            return 0.0

    def train(self, csv_files: list[str]) -> dict:
        """
        Train the risk assessment model on trading data.
        
        Args:
            csv_files: List of paths to CSV files with trading data
            
        Returns:
            Dictionary with training statistics
        """
        all_data = []

        # Load and process all CSV files
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file)
                all_data.append(df)
            except Exception as e:
                print(f"Error loading {csv_file}: {e}")

        if not all_data:
            raise ValueError("No valid CSV files provided for training")

        # Combine all data
        combined_df = pd.concat(all_data, ignore_index=True)

        # Extract hours
        combined_df['hour'] = combined_df['marketName'].apply(
            self._extract_hour_from_market_name
        )

        # Identify wins and losses by matching Buy/Redeem pairs
        # A loss is a Buy order without a corresponding Redeem
        combined_df['outcome'] = combined_df.apply(
            lambda row: self._calculate_trade_outcome(row, combined_df),
            axis=1
        )

        # Remove rows with missing hours
        combined_df = combined_df.dropna(subset=['hour'])
        combined_df['hour'] = combined_df['hour'].astype(int)

        # Calculate hourly statistics
        hourly_data = combined_df.groupby('hour').agg({
            'outcome': ['mean', 'std', 'count', 'min', 'max']
        }).reset_index()

        hourly_data.columns = [
            'hour', 'mean_outcome', 'std_outcome', 'trade_count',
            'min_outcome', 'max_outcome'
        ]

        # Fill missing hours with neutral values
        for hour in range(24):
            if hour not in hourly_data['hour'].values:
                hourly_data = pd.concat([
                    hourly_data,
                    pd.DataFrame({
                        'hour': [hour],
                        'mean_outcome': [1.0],
                        'std_outcome': [0.0],
                        'trade_count': [0],
                        'min_outcome': [1.0],
                        'max_outcome': [1.0]
                    })
                ], ignore_index=True)

        hourly_data = hourly_data.sort_values('hour').reset_index(drop=True)
        self.hourly_stats = hourly_data.to_dict('records')

        # Prepare training data: features are hourly statistics
        X = hourly_data[[
            'mean_outcome', 'std_outcome', 'trade_count', 
            'min_outcome', 'max_outcome'
        ]].values

        # Target: calculate risk score (inverse of win rate)
        # Higher win rate = lower risk = higher score
        y = hourly_data['mean_outcome'].values

        # Normalize features
        X_scaled = self.scaler.fit_transform(X)

        # Train the model
        self.model.fit(X_scaled, y)
        self.is_trained = True

        # Get feature importance
        feature_importance = {
            'mean_outcome': self.model.feature_importances_[0],
            'std_outcome': self.model.feature_importances_[1],
            'trade_count': self.model.feature_importances_[2],
            'min_outcome': self.model.feature_importances_[3],
            'max_outcome': self.model.feature_importances_[4],
        }

        stats = {
            'total_trades': len(combined_df),
            'hours_analyzed': len(hourly_data),
            'model_type': 'RandomForestRegressor',
            'feature_importance': feature_importance,
            'hourly_stats': hourly_data.to_dict('records')
        }

        return stats

    def _normalize_risk_score(self, raw_score: float) -> float:
        """
        Normalize win rate to 0-1 risk score with L-shaped distribution.
        
        Maps win rates (0-1) to risk scores with emphasis on low-risk times:
        - 0-10% win rate → 0.0-0.3 (high risk)
        - 10-20% win rate → 0.3-0.6 (medium risk)
        - 20%+ win rate → 0.6-1.0 (low risk - emphasized)
        
        0 = highest risk, 1 = lowest risk
        
        Args:
            raw_score: Win rate (0-1, typically 0.0-0.3 based on historical data)
            
        Returns:
            Normalized risk score (0-1) with L-shaped curve
        """
        # Clamp to observed range
        clamped = np.clip(raw_score, 0.0, 0.3)
        
        # Create L-shaped curve: accelerate the upper end
        # Use power function: x^0.5 creates emphasis on higher values
        # Maps: 0.0→0.0, 0.15→0.39, 0.3→1.0
        l_shaped = np.power(clamped / 0.3, 0.5)
        
        return float(np.clip(l_shaped, 0.0, 1.0))

    def get_risk_score(self, hour: int) -> float:
        """
        Get risk score for a specific hour.
        
        Args:
            hour: Hour in 24-hour format (0-23)
            
        Returns:
            Risk score from 0 (riskiest) to 1 (safest)
            
        Raises:
            ValueError: If model is not trained
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before getting risk scores")

        if not 0 <= hour <= 23:
            raise ValueError("Hour must be between 0 and 23")

        # Find hourly stats for this hour
        stats = next(
            (s for s in self.hourly_stats if s['hour'] == hour),
            None
        )

        if stats is None:
            raise ValueError(f"No stats found for hour {hour}")

        # Prepare features
        features = np.array([[
            stats['mean_outcome'],
            stats['std_outcome'],
            stats['trade_count'],
            stats['min_outcome'],
            stats['max_outcome']
        ]])

        features_scaled = self.scaler.transform(features)

        # Get prediction from model
        raw_prediction = self.model.predict(features_scaled)[0]

        # Normalize to 0-1 scale
        risk_score = self._normalize_risk_score(raw_prediction)

        return risk_score

    def get_risk_scores_all_hours(self) -> dict[int, float]:
        """
        Get risk scores for all 24 hours.
        
        Returns:
            Dictionary mapping hour (0-23) to risk score (0-1)
        """
        if not self.is_trained:
            raise ValueError("Model must be trained before getting risk scores")

        scores = {}
        for hour in range(24):
            scores[hour] = self.get_risk_score(hour)

        return scores

    def get_riskiest_hours(self, top_n: int = 5) -> list[Tuple[int, float]]:
        """
        Get the riskiest hours to trade.
        
        Args:
            top_n: Number of riskiest hours to return
            
        Returns:
            List of (hour, risk_score) tuples, ordered by risk (lowest score first)
        """
        scores = self.get_risk_scores_all_hours()
        sorted_hours = sorted(scores.items(), key=lambda x: x[1])
        return sorted_hours[:top_n]

    def get_safest_hours(self, top_n: int = 5) -> list[Tuple[int, float]]:
        """
        Get the safest hours to trade.
        
        Args:
            top_n: Number of safest hours to return
            
        Returns:
            List of (hour, risk_score) tuples, ordered by safety (highest score first)
        """
        scores = self.get_risk_scores_all_hours()
        sorted_hours = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_hours[:top_n]

    def get_risk_by_time_range(self, start_hour: int, end_hour: int) -> float:
        """
        Get average risk score for a time range.
        
        Args:
            start_hour: Starting hour (inclusive, 0-23)
            end_hour: Ending hour (inclusive, 0-23)
            
        Returns:
            Average risk score for the range
        """
        if start_hour > end_hour:
            raise ValueError("start_hour must be <= end_hour")

        scores = self.get_risk_scores_all_hours()
        range_scores = [
            scores[h] for h in range(start_hour, end_hour + 1)
        ]

        return float(np.mean(range_scores))


# Singleton instance for easy access
_risk_model: Optional[TimeOfDayRiskAssessment] = None


def initialize_risk_model(csv_files: list[str]) -> TimeOfDayRiskAssessment:
    """
    Initialize and train the global risk model.
    
    Args:
        csv_files: List of CSV file paths to train on
        
    Returns:
        Trained TimeOfDayRiskAssessment instance
    """
    global _risk_model
    _risk_model = TimeOfDayRiskAssessment()
    _risk_model.train(csv_files)
    return _risk_model


def get_risk_score(hour: int) -> float:
    """
    Get risk score for a given hour using the global model.
    
    Args:
        hour: Hour in 24-hour format (0-23)
        
    Returns:
        Risk score from 0 (riskiest) to 1 (safest)
        
    Raises:
        RuntimeError: If model not initialized
    """
    if _risk_model is None:
        raise RuntimeError(
            "Risk model not initialized. Call initialize_risk_model() first."
        )
    return _risk_model.get_risk_score(hour)


def get_current_hour_risk() -> float:
    """
    Get risk score for the current hour.
    
    Returns:
        Risk score from 0 (riskiest) to 1 (safest)
    """
    current_hour = datetime.now().hour
    return get_risk_score(current_hour)


def initialize_from_workspace(workspace_root: str) -> TimeOfDayRiskAssessment:
    """
    Auto-discover and train on the latest 2 CSV files in the workspace.
    Weights the most recent file more heavily.
    
    Args:
        workspace_root: Root directory of the workspace
        
    Returns:
        Trained TimeOfDayRiskAssessment instance
    """
    workspace_path = Path(workspace_root)
    csv_files = list(workspace_path.glob('**/market_export.csv'))

    if not csv_files:
        raise ValueError(f"No market_export.csv files found in {workspace_root}")

    # Sort by modification time (newest first)
    csv_files_sorted = sorted(csv_files, key=lambda f: f.stat().st_mtime, reverse=True)
    
    # Take only the latest 2 files
    latest_csvs = csv_files_sorted[:2]
    
    # Weight the most recent file more heavily by duplicating it
    # Latest file (index 0) gets 2x weight, older file (index 1) gets 1x weight
    csv_paths = [str(latest_csvs[0])] * 2  # Most recent, duplicated for 2x weight
    if len(latest_csvs) > 1:
        csv_paths.append(str(latest_csvs[1]))  # Second most recent, 1x weight
    
    print(f"Found {len(csv_files)} CSV files total")
    print(f"Using latest 2 files for training (with 2x weight on most recent):")
    for i, csv_file in enumerate(latest_csvs):
        weight = "2x" if i == 0 else "1x"
        print(f"  {weight}: {csv_file.parent.name}/{csv_file.name}")
    
    return initialize_risk_model(csv_paths)
