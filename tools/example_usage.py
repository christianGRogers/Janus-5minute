#!/usr/bin/env python3
"""
Example: Using the BotPerformanceVisualizer as a Python module

This script demonstrates how to use the visualizer programmatically
instead of from the command line.
"""

from pathlib import Path
from visualize_performance import BotPerformanceVisualizer


def main():
    """Example usage of BotPerformanceVisualizer."""

    # Example 1: Basic usage
    print("=" * 60)
    print("Example 1: Basic Visualization")
    print("=" * 60)

    csv_file = "market_performance.csv"
    output_dir = "./charts"

    try:
        viz = BotPerformanceVisualizer(csv_file, output_dir)
        viz.generate_all_charts()
    except FileNotFoundError:
        print(f"Note: Example file '{csv_file}' not found. Use your actual CSV file.")

    # Example 2: Custom analysis
    print("\n" + "=" * 60)
    print("Example 2: Custom Analysis")
    print("=" * 60)

    try:
        viz = BotPerformanceVisualizer("market_performance.csv")

        # Access the underlying dataframe for custom analysis
        df = viz.df

        print(f"\nDataFrame shape: {df.shape}")
        print(f"Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")

        # Calculate custom statistics
        total_trades = len(df)
        win_rate = (df["correct_positions"].sum() / (df["correct_positions"].sum() + df["wrong_positions"].sum()) * 100)
        avg_profit = df["net_profit_usdc"].mean()
        total_profit = df["net_profit_usdc"].sum()

        print(f"\nCustom Statistics:")
        print(f"  Total Trades: {total_trades}")
        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Average Profit: ${avg_profit:.2f}")
        print(f"  Total Profit: ${total_profit:.2f}")

    except FileNotFoundError:
        print("Note: Example requires a CSV file in current directory.")

    # Example 3: Generate specific charts
    print("\n" + "=" * 60)
    print("Example 3: Selective Chart Generation")
    print("=" * 60)

    try:
        viz = BotPerformanceVisualizer("market_performance.csv", "./charts")

        # Generate only specific charts
        print("Generating profit timeline chart...")
        viz.plot_profit_timeline()

        print("Generating win rate analysis chart...")
        viz.plot_win_rate_analysis()

        # Skip others for faster processing
        print("\nSkipped other charts for this example.")

    except FileNotFoundError:
        print("Note: Example requires a CSV file in current directory.")

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
