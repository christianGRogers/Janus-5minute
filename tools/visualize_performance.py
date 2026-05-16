#!/usr/bin/env python3
"""
Janus Bot Performance Visualization Tool

Visualizes trading performance data from CSV log files using matplotlib and seaborn.
Generates various charts including profit trends, win rates, price analysis, and more.

Usage:
    python visualize_performance.py <csv_file> [--output <output_dir>]
    python visualize_performance.py logs/markets/2026-04-23_22-15-45/market_performance.csv
    python visualize_performance.py market_performance.csv --output ./charts
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from matplotlib.gridspec import GridSpec


class BotPerformanceVisualizer:
    """Visualizes Janus Bot trading performance data."""

    def __init__(self, csv_file: str, output_dir: str = None):
        """
        Initialize the visualizer.

        Args:
            csv_file: Path to the market_performance.csv file
            output_dir: Directory to save output charts (default: ./charts)
        """
        self.csv_file = Path(csv_file)
        self.output_dir = Path(output_dir) if output_dir else Path("./charts")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set style
        sns.set_theme(style="darkgrid")
        plt.rcParams["figure.figsize"] = (14, 8)
        plt.rcParams["font.size"] = 10

        # Load data
        self.df = self._load_data()
        self._prepare_data()

    def _load_data(self) -> pd.DataFrame:
        """Load and validate CSV data."""
        if not self.csv_file.exists():
            raise FileNotFoundError(f"CSV file not found: {self.csv_file}")

        df = pd.read_csv(self.csv_file)

        # Validate required columns
        required_cols = [
            "timestamp",
            "net_profit_usdc",
            "win_rate_pct",
            "position_count",
            "correct_positions",
            "wrong_positions",
            "avg_entry_price",
            "avg_exit_price",
            "gross_profit_usdc",
            "total_fees_usdc",
            "account_balance_usdc",
            "cumulative_profit_usdc",
        ]

        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(
                f"CSV is missing required columns: {missing_cols}\n"
                f"Available columns: {df.columns.tolist()}"
            )

        # Convert timestamp to datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        print(f"✅ Loaded {len(df)} trades from {self.csv_file.name}")
        return df

    def _prepare_data(self):
        """Prepare data for visualization."""
        # Calculate accurate balance: starting balance (10000) + cumulative profit
        starting_balance = 20.0
        self.df["calculated_balance"] = starting_balance + self.df["cumulative_profit_usdc"]
        self.starting_balance = starting_balance
        
        self.df["profit_color"] = self.df["net_profit_usdc"].apply(
            lambda x: "green" if x > 0 else "red"
        )
        self.df["win"] = self.df["correct_positions"] > 0
        self.df["loss"] = self.df["wrong_positions"] > 0
        self.df["hour"] = self.df["timestamp"].dt.hour
        self.df["date"] = self.df["timestamp"].dt.date

    def _save_figure(self, filename: str, fig: plt.Figure = None):
        """Save figure to output directory."""
        if fig is None:
            fig = plt.gcf()
        filepath = self.output_dir / filename
        fig.tight_layout()
        fig.savefig(filepath, dpi=300, bbox_inches="tight")
        print(f"📊 Saved: {filepath}")
        plt.close(fig)

    def plot_profit_timeline(self):
        """Plot net profit over time with cumulative profit."""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

        # Individual trade profits
        colors = [
            "green" if x > 0 else "red" for x in self.df["net_profit_usdc"]
        ]
        ax1.bar(self.df["timestamp"], self.df["net_profit_usdc"], color=colors, alpha=0.7)
        ax1.axhline(y=0, color="black", linestyle="-", linewidth=0.5)
        ax1.set_ylabel("Net Profit (USDC)", fontsize=12, fontweight="bold")
        ax1.set_title("Trade Profits Over Time", fontsize=14, fontweight="bold")
        ax1.grid(True, alpha=0.3)

        # Cumulative profit
        ax2.plot(
            self.df["timestamp"],
            self.df["cumulative_profit_usdc"],
            marker="o",
            linewidth=2,
            markersize=6,
            color="blue",
        )
        ax2.fill_between(
            self.df["timestamp"],
            self.df["cumulative_profit_usdc"],
            alpha=0.3,
            color="blue",
        )
        ax2.axhline(y=0, color="black", linestyle="--", linewidth=1)
        ax2.set_xlabel("Time", fontsize=12, fontweight="bold")
        ax2.set_ylabel("Cumulative Profit (USDC)", fontsize=12, fontweight="bold")
        ax2.set_title("Cumulative Profit Trend", fontsize=14, fontweight="bold")
        ax2.grid(True, alpha=0.3)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

        self._save_figure("01_profit_timeline.png", fig)

    def plot_win_rate_analysis(self):
        """Plot win rate and win/loss distribution."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(
            2, 2, figsize=(14, 10)
        )

        # Win rate over time
        ax1.plot(
            self.df["timestamp"],
            self.df["win_rate_pct"],
            marker="o",
            linewidth=2,
            markersize=6,
            color="purple",
        )
        ax1.axhline(y=50, color="orange", linestyle="--", linewidth=1, label="50% (Break-even)")
        ax1.fill_between(
            self.df["timestamp"], self.df["win_rate_pct"], 50, alpha=0.2, color="purple"
        )
        ax1.set_ylabel("Win Rate (%)", fontsize=11, fontweight="bold")
        ax1.set_title("Win Rate Over Time", fontsize=12, fontweight="bold")
        ax1.set_ylim([0, 105])
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Win vs Loss count
        wins = self.df["correct_positions"].sum()
        losses = self.df["wrong_positions"].sum()
        ax2.bar(["Wins", "Losses"], [wins, losses], color=["green", "red"], alpha=0.7)
        ax2.set_ylabel("Count", fontsize=11, fontweight="bold")
        ax2.set_title(f"Total Wins vs Losses (Win Rate: {(wins/(wins+losses)*100):.1f}%)", fontsize=12, fontweight="bold")
        for i, v in enumerate([wins, losses]):
            ax2.text(i, v + 0.1, str(int(v)), ha="center", va="bottom", fontweight="bold")
        ax2.grid(True, alpha=0.3, axis="y")

        # Positions per trade
        ax3.bar(
            range(len(self.df)),
            self.df["position_count"],
            color="steelblue",
            alpha=0.7,
        )
        ax3.set_xlabel("Trade Number", fontsize=11, fontweight="bold")
        ax3.set_ylabel("Positions", fontsize=11, fontweight="bold")
        ax3.set_title("Positions Per Trade", fontsize=12, fontweight="bold")
        ax3.grid(True, alpha=0.3, axis="y")

        # Profit percentage
        profit_pct = (self.df["net_profit_usdc"] / self.df["account_balance_usdc"] * 100).abs()
        colors = [
            "green" if x > 0 else "red" for x in self.df["net_profit_usdc"]
        ]
        ax4.bar(range(len(self.df)), profit_pct, color=colors, alpha=0.7)
        ax4.set_xlabel("Trade Number", fontsize=11, fontweight="bold")
        ax4.set_ylabel("Profit %", fontsize=11, fontweight="bold")
        ax4.set_title("Profit as % of Account", fontsize=12, fontweight="bold")
        ax4.grid(True, alpha=0.3, axis="y")

        self._save_figure("02_win_rate_analysis.png", fig)

    def plot_price_analysis(self):
        """Plot entry/exit price analysis."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(
            2, 2, figsize=(14, 10)
        )

        # Entry vs Exit prices
        x_pos = range(len(self.df))
        width = 0.35
        ax1.bar(
            [x - width / 2 for x in x_pos],
            self.df["avg_entry_price"],
            width,
            label="Entry",
            alpha=0.8,
            color="steelblue",
        )
        ax1.bar(
            [x + width / 2 for x in x_pos],
            self.df["avg_exit_price"],
            width,
            label="Exit",
            alpha=0.8,
            color="coral",
        )
        ax1.set_xlabel("Trade Number", fontsize=11, fontweight="bold")
        ax1.set_ylabel("Price", fontsize=11, fontweight="bold")
        ax1.set_title("Entry vs Exit Prices", fontsize=12, fontweight="bold")
        ax1.legend()
        ax1.grid(True, alpha=0.3, axis="y")

        # Price spread (Entry - Exit)
        spread = self.df["avg_entry_price"] - self.df["avg_exit_price"]
        colors = ["green" if x > 0 else "red" for x in spread]
        ax2.bar(x_pos, spread, color=colors, alpha=0.7)
        ax2.axhline(y=0, color="black", linestyle="-", linewidth=0.5)
        ax2.set_xlabel("Trade Number", fontsize=11, fontweight="bold")
        ax2.set_ylabel("Price Spread", fontsize=11, fontweight="bold")
        ax2.set_title("Entry-Exit Price Spread (Positive = Short Win)", fontsize=12, fontweight="bold")
        ax2.grid(True, alpha=0.3, axis="y")

        # Entry price distribution
        ax3.hist(
            self.df["avg_entry_price"],
            bins=15,
            color="steelblue",
            alpha=0.7,
            edgecolor="black",
        )
        ax3.set_xlabel("Entry Price", fontsize=11, fontweight="bold")
        ax3.set_ylabel("Frequency", fontsize=11, fontweight="bold")
        ax3.set_title("Entry Price Distribution", fontsize=12, fontweight="bold")
        ax3.grid(True, alpha=0.3, axis="y")

        # Entry price vs Profit
        scatter = ax4.scatter(
            self.df["avg_entry_price"],
            self.df["net_profit_usdc"],
            c=self.df["net_profit_usdc"],
            cmap="RdYlGn",
            s=100,
            alpha=0.7,
            edgecolors="black",
        )
        ax4.axhline(y=0, color="black", linestyle="--", linewidth=1)
        ax4.set_xlabel("Entry Price", fontsize=11, fontweight="bold")
        ax4.set_ylabel("Net Profit (USDC)", fontsize=11, fontweight="bold")
        ax4.set_title("Entry Price vs Profit", fontsize=12, fontweight="bold")
        cbar = plt.colorbar(scatter, ax=ax4)
        cbar.set_label("Profit (USDC)", fontsize=10)
        ax4.grid(True, alpha=0.3)

        self._save_figure("03_price_analysis.png", fig)

    def plot_fee_analysis(self):
        """Plot fee impact on profits."""
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(
            2, 2, figsize=(14, 10)
        )

        # Gross vs Net profit
        x_pos = range(len(self.df))
        width = 0.35
        ax1.bar(
            [x - width / 2 for x in x_pos],
            self.df["gross_profit_usdc"],
            width,
            label="Gross",
            alpha=0.8,
            color="lightgreen",
        )
        ax1.bar(
            [x + width / 2 for x in x_pos],
            self.df["net_profit_usdc"],
            width,
            label="Net",
            alpha=0.8,
            color="darkgreen",
        )
        ax1.axhline(y=0, color="black", linestyle="-", linewidth=0.5)
        ax1.set_xlabel("Trade Number", fontsize=11, fontweight="bold")
        ax1.set_ylabel("Profit (USDC)", fontsize=11, fontweight="bold")
        ax1.set_title("Gross vs Net Profit (Fee Impact)", fontsize=12, fontweight="bold")
        ax1.legend()
        ax1.grid(True, alpha=0.3, axis="y")

        # Total fees per trade
        ax2.bar(x_pos, self.df["total_fees_usdc"], color="orange", alpha=0.7)
        ax2.set_xlabel("Trade Number", fontsize=11, fontweight="bold")
        ax2.set_ylabel("Fees (USDC)", fontsize=11, fontweight="bold")
        ax2.set_title("Fees Per Trade", fontsize=12, fontweight="bold")
        ax2.grid(True, alpha=0.3, axis="y")

        # Fee percentage of gross profit
        fee_pct = (
            self.df["total_fees_usdc"] / self.df["gross_profit_usdc"].abs() * 100
        ).fillna(0)
        ax3.bar(x_pos, fee_pct, color="red", alpha=0.7)
        ax3.set_xlabel("Trade Number", fontsize=11, fontweight="bold")
        ax3.set_ylabel("Fee %", fontsize=11, fontweight="bold")
        ax3.set_title("Fees as % of Gross Profit", fontsize=12, fontweight="bold")
        ax3.grid(True, alpha=0.3, axis="y")

        # Cumulative fees
        ax4.plot(
            self.df["timestamp"],
            self.df["total_fees_usdc"].cumsum(),
            marker="o",
            linewidth=2,
            markersize=6,
            color="red",
        )
        ax4.fill_between(
            self.df["timestamp"],
            self.df["total_fees_usdc"].cumsum(),
            alpha=0.3,
            color="red",
        )
        ax4.set_xlabel("Time", fontsize=11, fontweight="bold")
        ax4.set_ylabel("Cumulative Fees (USDC)", fontsize=11, fontweight="bold")
        ax4.set_title("Cumulative Fees Over Time", fontsize=12, fontweight="bold")
        ax4.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax4.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax4.xaxis.get_majorticklabels(), rotation=45)
        ax4.grid(True, alpha=0.3)

        self._save_figure("04_fee_analysis.png", fig)

    def plot_account_balance(self):
        """Plot account balance over time (calculated from starting balance + cumulative profit)."""
        fig, ax = plt.subplots(figsize=(14, 6))

        ax.plot(
            self.df["timestamp"],
            self.df["calculated_balance"],
            marker="o",
            linewidth=2.5,
            markersize=7,
            color="darkblue",
            label="Account Balance (20 + Cumulative Profit)",
        )
        
        # Add starting balance line
        ax.axhline(
            y=self.starting_balance,
            color="gray",
            linestyle="--",
            linewidth=1,
            alpha=0.7,
            label=f"Starting Balance: ${self.starting_balance:,.2f}",
        )

        ax.fill_between(
            self.df["timestamp"],
            self.df["calculated_balance"],
            self.starting_balance,
            alpha=0.2,
            color="darkblue",
        )

        ax.set_xlabel("Time", fontsize=12, fontweight="bold")
        ax.set_ylabel("Account Balance (USDC)", fontsize=12, fontweight="bold")
        ax.set_title("Account Balance Progression", fontsize=14, fontweight="bold")
        ax.legend(fontsize=11)
        ax.grid(True, alpha=0.3)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

        self._save_figure("05_account_balance.png", fig)

    def plot_summary_stats(self):
        """Create summary statistics dashboard."""
        fig = plt.figure(figsize=(14, 10))
        gs = GridSpec(3, 3, figure=fig, hspace=0.4, wspace=0.3)

        # Summary statistics
        total_trades = len(self.df)
        wins = self.df["correct_positions"].sum()
        losses = self.df["wrong_positions"].sum()
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        total_profit = self.df["net_profit_usdc"].sum()
        total_fees = self.df["total_fees_usdc"].sum()
        avg_trade_profit = total_profit / total_trades if total_trades > 0 else 0
        
        # Use fixed starting balance of 20
        starting_balance = self.starting_balance
        final_balance = self.df["calculated_balance"].iloc[-1]
        roi = ((final_balance - starting_balance) / starting_balance * 100)
        
        # Calculate hours traded
        time_range = self.df["timestamp"].max() - self.df["timestamp"].min()
        hours_traded = time_range.total_seconds() / 3600

        stats_text = f"""
        📊 TRADING PERFORMANCE SUMMARY
        {'='*50}
        
        Total Trades: {total_trades}
        Wins: {int(wins)} | Losses: {int(losses)}
        Win Rate: {win_rate:.1f}%
        
        {'='*50}
        Total Net Profit: ${total_profit:,.2f}
        Total Fees Paid: ${total_fees:,.2f}
        Avg Profit/Trade: ${avg_trade_profit:,.2f}
        
        {'='*50}
        Starting Balance: ${starting_balance:,.2f}
        Final Balance: ${final_balance:,.2f}
        ROI: {roi:.2f}%
        
        {'='*50}
        Hours Traded: {hours_traded:.1f} hours
        
        {'='*50}
        """

        ax = fig.add_subplot(gs[0, :])
        ax.text(
            0.5,
            0.5,
            stats_text,
            transform=ax.transAxes,
            fontsize=11,
            verticalalignment="center",
            horizontalalignment="center",
            fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
        )
        ax.axis("off")

        # Top 3 best trades
        best_trades = self.df.nlargest(3, "net_profit_usdc")[["timestamp", "net_profit_usdc", "win_rate_pct"]]
        ax1 = fig.add_subplot(gs[1, 0])
        ax1.axis("off")
        best_text = "🏆 Top 3 Trades\n" + "\n".join([
            f"{i+1}. ${row['net_profit_usdc']:,.2f}" 
            for i, (_, row) in enumerate(best_trades.iterrows())
        ])
        ax1.text(0.1, 0.9, best_text, transform=ax1.transAxes, fontsize=10, verticalalignment="top", fontfamily="monospace")

        # Worst 3 trades
        worst_trades = self.df.nsmallest(3, "net_profit_usdc")[["timestamp", "net_profit_usdc", "win_rate_pct"]]
        ax2 = fig.add_subplot(gs[1, 1])
        ax2.axis("off")
        worst_text = "📉 Worst 3 Trades\n" + "\n".join([
            f"{i+1}. ${row['net_profit_usdc']:,.2f}" 
            for i, (_, row) in enumerate(worst_trades.iterrows())
        ])
        ax2.text(0.1, 0.9, worst_text, transform=ax2.transAxes, fontsize=10, verticalalignment="top", fontfamily="monospace")

        # Average stats
        ax3 = fig.add_subplot(gs[1, 2])
        ax3.axis("off")
        avg_text = f"""📈 Averages
Entry Price: ${self.df['avg_entry_price'].mean():.4f}
Exit Price: ${self.df['avg_exit_price'].mean():.4f}
Trade Size: {self.df['total_size_traded'].mean():.1f}"""
        ax3.text(0.1, 0.9, avg_text, transform=ax3.transAxes, fontsize=10, verticalalignment="top", fontfamily="monospace")

        # Distribution pie chart
        ax4 = fig.add_subplot(gs[2, 0])
        colors = ["green", "red"]
        ax4.pie(
            [wins, losses],
            labels=["Wins", "Losses"],
            colors=colors,
            autopct="%1.1f%%",
            startangle=90,
        )
        ax4.set_title("Win/Loss Distribution", fontweight="bold")

        # Hourly performance
        ax5 = fig.add_subplot(gs[2, 1:])
        hourly_profit = self.df.groupby("hour")["net_profit_usdc"].sum()
        colors = ["green" if x > 0 else "red" for x in hourly_profit.values]
        ax5.bar(hourly_profit.index, hourly_profit.values, color=colors, alpha=0.7)
        ax5.axhline(y=0, color="black", linestyle="-", linewidth=0.5)
        ax5.set_xlabel("Hour of Day", fontsize=11, fontweight="bold")
        ax5.set_ylabel("Profit (USDC)", fontsize=11, fontweight="bold")
        ax5.set_title("Hourly Profit Distribution", fontsize=12, fontweight="bold")
        ax5.grid(True, alpha=0.3, axis="y")

        self._save_figure("06_summary_stats.png", fig)

    def generate_all_charts(self):
        """Generate all available charts."""
        print("\n📊 Generating visualization charts...\n")

        try:
            print("1. Plotting profit timeline...")
            self.plot_profit_timeline()

            print("2. Plotting win rate analysis...")
            self.plot_win_rate_analysis()

            print("3. Plotting price analysis...")
            self.plot_price_analysis()

            print("4. Plotting fee analysis...")
            self.plot_fee_analysis()

            print("5. Plotting account balance...")
            self.plot_account_balance()

            print("6. Plotting summary statistics...")
            self.plot_summary_stats()

            print(f"\n✅ All charts generated successfully!")
            print(f"📁 Output directory: {self.output_dir.resolve()}\n")

        except Exception as e:
            print(f"\n❌ Error generating charts: {e}")
            raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Visualize Janus Bot trading performance data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python visualize_performance.py market_performance.csv
  python visualize_performance.py logs/markets/2026-04-23_22-15-45/market_performance.csv --output ./charts
  python visualize_performance.py ~/downloads/performance.csv --output /tmp/charts
        """,
    )

    parser.add_argument(
        "--csv_file",
        help="Path to market_performance.csv file",
    )

    parser.add_argument(
        "--output",
        "-o",
        default="./charts",
        help="Output directory for charts (default: ./charts)",
    )

    args = parser.parse_args()

    try:
        visualizer = BotPerformanceVisualizer(args.csv_file, args.output)
        visualizer.generate_all_charts()

    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
