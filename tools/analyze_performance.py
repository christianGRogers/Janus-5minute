#!/usr/bin/env python3
"""
Market Performance Analysis and Visualization Script

Reads the market performance logs and creates visualizations for analysis.
Supports both JSON and CSV log formats.

Usage:
    python3 analyze_performance.py <log_directory>
"""

import os
import sys
import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from pathlib import Path

# Set style for better-looking plots
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)


class PerformanceAnalyzer:
    def __init__(self, log_dir):
        self.log_dir = Path(log_dir)
        self.data = None
        self.results_dir = self.log_dir / "analysis"
        self.results_dir.mkdir(exist_ok=True)

    def load_data(self):
        """Load CSV data from the log directory"""
        csv_file = self.log_dir / "market_performance.csv"
        
        if not csv_file.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_file}")
        
        self.data = pd.read_csv(csv_file)
        self.data['timestamp'] = pd.to_datetime(self.data['timestamp'])
        return self.data

    def print_summary_statistics(self):
        """Print summary statistics of the performance"""
        if self.data is None:
            self.load_data()
        
        print("\n" + "="*60)
        print("MARKET PERFORMANCE SUMMARY")
        print("="*60)
        
        total_markets = len(self.data)
        total_positions = self.data['position_count'].sum()
        winning_positions = self.data['correct_positions'].sum()
        losing_positions = self.data['wrong_positions'].sum()
        
        print(f"\nMarkets Analyzed: {total_markets}")
        print(f"Total Positions: {total_positions}")
        print(f"Winning Positions: {winning_positions} ({100*winning_positions/total_positions:.1f}%)")
        print(f"Losing Positions: {losing_positions} ({100*losing_positions/total_positions:.1f}%)")
        
        print(f"\nAverage Win Rate per Market: {self.data['win_rate_pct'].mean():.2f}%")
        print(f"Total Net Profit: ${self.data['net_profit_usdc'].sum():.2f}")
        print(f"Average Net Profit per Market: ${self.data['net_profit_usdc'].mean():.2f}")
        print(f"Total Fees Paid: ${self.data['total_fees_usdc'].sum():.2f}")
        
        print(f"\nBest Market: {self.data.loc[self.data['net_profit_usdc'].idxmax(), 'market_id']}")
        print(f"  Profit: ${self.data['net_profit_usdc'].max():.2f}")
        
        worst_idx = self.data['net_profit_usdc'].idxmin()
        if self.data.loc[worst_idx, 'net_profit_usdc'] < 0:
            print(f"Worst Market: {self.data.loc[worst_idx, 'market_id']}")
            print(f"  Loss: ${self.data.loc[worst_idx, 'net_profit_usdc']:.2f}")
        
        print("\n" + "="*60 + "\n")

    def plot_cumulative_profit(self):
        """Plot cumulative profit over time"""
        if self.data is None:
            self.load_data()
        
        self.data = self.data.sort_values('timestamp')
        
        fig, ax = plt.subplots(figsize=(14, 6))
        
        ax.plot(self.data['timestamp'], self.data['cumulative_profit_usdc'], 
                linewidth=2, marker='o', markersize=4, label='Cumulative Profit')
        ax.axhline(y=0, color='r', linestyle='--', alpha=0.5, label='Break Even')
        
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel('Profit (USDC)', fontsize=12)
        ax.set_title('Cumulative Profit Over Time', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
        ax.legend()
        
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(self.results_dir / "cumulative_profit.png", dpi=150, bbox_inches='tight')
        print("✓ Saved: cumulative_profit.png")
        plt.close()

    def plot_win_rate_by_market(self):
        """Plot win rate for each market"""
        if self.data is None:
            self.load_data()
        
        fig, ax = plt.subplots(figsize=(14, 6))
        
        colors = ['green' if x > 50 else 'red' for x in self.data['win_rate_pct']]
        ax.bar(range(len(self.data)), self.data['win_rate_pct'], color=colors, alpha=0.7)
        ax.axhline(y=50, color='black', linestyle='--', alpha=0.5, label='50% Win Rate')
        
        ax.set_xlabel('Market Index', fontsize=12)
        ax.set_ylabel('Win Rate (%)', fontsize=12)
        ax.set_title('Win Rate by Market', fontsize=14, fontweight='bold')
        ax.set_ylim(0, 100)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        plt.savefig(self.results_dir / "win_rate_by_market.png", dpi=150, bbox_inches='tight')
        print("✓ Saved: win_rate_by_market.png")
        plt.close()

    def plot_profit_distribution(self):
        """Plot histogram of profit per market"""
        if self.data is None:
            self.load_data()
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        # Net profit histogram
        ax1.hist(self.data['net_profit_usdc'], bins=20, color='steelblue', alpha=0.7, edgecolor='black')
        ax1.axvline(self.data['net_profit_usdc'].mean(), color='red', linestyle='--', 
                   linewidth=2, label=f"Mean: ${self.data['net_profit_usdc'].mean():.2f}")
        ax1.axvline(self.data['net_profit_usdc'].median(), color='green', linestyle='--', 
                   linewidth=2, label=f"Median: ${self.data['net_profit_usdc'].median():.2f}")
        ax1.set_xlabel('Net Profit per Market (USDC)', fontsize=11)
        ax1.set_ylabel('Frequency', fontsize=11)
        ax1.set_title('Distribution of Net Profit', fontsize=12, fontweight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3, axis='y')
        
        # Average profit % histogram
        ax2.hist(self.data['avg_profit_pct'], bins=20, color='orange', alpha=0.7, edgecolor='black')
        ax2.axvline(self.data['avg_profit_pct'].mean(), color='red', linestyle='--', 
                   linewidth=2, label=f"Mean: {self.data['avg_profit_pct'].mean():.2f}%")
        ax2.set_xlabel('Average Profit per Position (%)', fontsize=11)
        ax2.set_ylabel('Frequency', fontsize=11)
        ax2.set_title('Distribution of Per-Position Profit %', fontsize=12, fontweight='bold')
        ax2.legend()
        ax2.grid(True, alpha=0.3, axis='y')
        
        plt.tight_layout()
        plt.savefig(self.results_dir / "profit_distribution.png", dpi=150, bbox_inches='tight')
        print("✓ Saved: profit_distribution.png")
        plt.close()

    def plot_fee_impact(self):
        """Plot the impact of fees on profitability"""
        if self.data is None:
            self.load_data()
        
        fig, ax = plt.subplots(figsize=(14, 6))
        
        x = range(len(self.data))
        width = 0.35
        
        ax.bar([i - width/2 for i in x], self.data['gross_profit_usdc'], width, 
               label='Gross Profit', alpha=0.8, color='lightgreen')
        ax.bar([i + width/2 for i in x], self.data['net_profit_usdc'], width, 
               label='Net Profit (after fees)', alpha=0.8, color='darkgreen')
        
        ax.set_xlabel('Market Index', fontsize=12)
        ax.set_ylabel('Profit (USDC)', fontsize=12)
        ax.set_title('Impact of Fees on Profitability', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        
        plt.tight_layout()
        plt.savefig(self.results_dir / "fee_impact.png", dpi=150, bbox_inches='tight')
        print("✓ Saved: fee_impact.png")
        plt.close()

    def plot_position_count_vs_profit(self):
        """Scatter plot of position count vs profit"""
        if self.data is None:
            self.load_data()
        
        fig, ax = plt.subplots(figsize=(10, 7))
        
        # Color by resolution
        colors = {'UP': 'blue', 'DOWN': 'red'}
        for resolution in self.data['resolution'].unique():
            mask = self.data['resolution'] == resolution
            ax.scatter(self.data.loc[mask, 'position_count'], 
                      self.data.loc[mask, 'net_profit_usdc'],
                      label=resolution, s=100, alpha=0.6, edgecolors='black')
        
        ax.set_xlabel('Number of Positions', fontsize=12)
        ax.set_ylabel('Net Profit (USDC)', fontsize=12)
        ax.set_title('Position Count vs Profit by Market Resolution', fontsize=14, fontweight='bold')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        
        plt.tight_layout()
        plt.savefig(self.results_dir / "position_count_vs_profit.png", dpi=150, bbox_inches='tight')
        print("✓ Saved: position_count_vs_profit.png")
        plt.close()

    def export_detailed_csv(self):
        """Export detailed analysis to CSV"""
        if self.data is None:
            self.load_data()
        
        # Sort by timestamp
        sorted_data = self.data.sort_values('timestamp').reset_index(drop=True)
        sorted_data.to_csv(self.results_dir / "detailed_analysis.csv", index=False)
        print("✓ Saved: detailed_analysis.csv")

    def generate_all_visualizations(self):
        """Generate all visualizations"""
        print("\nGenerating visualizations...")
        self.load_data()
        self.print_summary_statistics()
        self.plot_cumulative_profit()
        self.plot_win_rate_by_market()
        self.plot_profit_distribution()
        self.plot_fee_impact()
        self.plot_position_count_vs_profit()
        self.export_detailed_csv()
        print(f"\n✓ All visualizations saved to: {self.results_dir}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_performance.py <log_directory>")
        print("\nExample:")
        print("  python3 analyze_performance.py ./logs/markets/2026-04-23_14-30-45")
        sys.exit(1)
    
    log_dir = sys.argv[1]
    
    if not Path(log_dir).exists():
        print(f"Error: Directory not found: {log_dir}")
        sys.exit(1)
    
    try:
        analyzer = PerformanceAnalyzer(log_dir)
        analyzer.generate_all_visualizations()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
