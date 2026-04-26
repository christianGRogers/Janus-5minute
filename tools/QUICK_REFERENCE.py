#!/usr/bin/env python3
"""
Quick Reference: Janus Bot Visualization Tools

This file is a quick lookup guide for the visualization toolkit.
"""

QUICK_START = """
╔════════════════════════════════════════════════════════════════════════════════╗
║                    🎉 VISUALIZATION TOOLKIT - QUICK START 🎉                  ║
╚════════════════════════════════════════════════════════════════════════════════╝

📦 INSTALLATION
================
pip install -r tools/requirements-analysis.txt


🚀 USAGE (Choose One)
=======================

Option 1 - Linux/macOS (Bash)
───────────────────────────
cd tools
bash visualize.sh ../logs/markets/2026-04-23_22-15-45/market_performance.csv

Option 2 - Windows (Batch)
──────────────────────────
cd tools
visualize.bat ..\logs\markets\2026-04-23_22-15-45\market_performance.csv

Option 3 - Direct Python (All Platforms)
─────────────────────────────────────────
python tools/visualize_performance.py market_performance.csv
python tools/visualize_performance.py market_performance.csv --output ~/charts


📊 OUTPUT CHARTS
=================
All saved as PNG files (300 DPI):

1. 01_profit_timeline.png         - Individual & cumulative profits
2. 02_win_rate_analysis.png       - Win rate trends & distribution  
3. 03_price_analysis.png          - Entry/exit price analysis
4. 04_fee_analysis.png            - Fee impact analysis
5. 05_account_balance.png         - Account balance progression
6. 06_summary_stats.png           - Dashboard with key metrics


🎯 TYPICAL WORKFLOW
====================

Step 1: Find your log file
   Location: logs/markets/{date_time}/market_performance.csv
   Example: logs/markets/2026-04-23_22-15-45/market_performance.csv

Step 2: Install dependencies (first time only)
   pip install -r tools/requirements-analysis.txt

Step 3: Run visualization
   python tools/visualize_performance.py <path_to_csv>

Step 4: View generated charts
   Open the PNG files in your image viewer


💡 COMMON COMMANDS
===================

Basic usage
──────────
python tools/visualize_performance.py market_performance.csv

Custom output directory
───────────────────────
python tools/visualize_performance.py market_performance.csv --output ~/Desktop/charts

Full path example
─────────────────
python tools/visualize_performance.py /home/user/Downloads/market_performance.csv

Help/Options
────────────
python tools/visualize_performance.py --help


🔧 PYTHON USAGE
================

As a module:
───────────
from tools.visualize_performance import BotPerformanceVisualizer

viz = BotPerformanceVisualizer('market_performance.csv')
viz.generate_all_charts()

Custom analysis:
───────────────
viz = BotPerformanceVisualizer('market_performance.csv')
df = viz.df
print(df['net_profit_usdc'].sum())  # Total profit


📁 FILE STRUCTURE
==================

tools/
├── visualize_performance.py      # Main tool (500+ lines)
├── visualize.sh                  # Linux/macOS script
├── visualize.bat                 # Windows script
├── example_usage.py              # Code examples
├── __init__.py                   # Python package
├── requirements-analysis.txt     # Dependencies
├── README.md                     # Full documentation
├── VISUALIZATION_QUICKSTART.md   # Quick reference
├── INDEX.md                      # Directory index
├── SUMMARY.md                    # Overview
└── QUICK_REFERENCE.py            # This file


📋 EXPECTED CSV COLUMNS
========================

timestamp                    - Trade timestamp
market_id                   - Market identifier
window_duration_sec         - 300 (5 minutes)
position_count              - Number of positions
correct_positions           - Winning positions
wrong_positions             - Losing positions
win_rate_pct                - Win rate percentage
gross_profit_usdc           - Profit before fees
total_fees_usdc             - Fees paid
net_profit_usdc             - Profit after fees
avg_profit_pct              - Profit percentage
avg_entry_price             - Entry price
avg_exit_price              - Exit price
total_size_traded           - Trade size
final_up_price              - Final UP price
final_down_price            - Final DOWN price
resolution                  - UP or DOWN result
account_balance_usdc        - Account balance
cumulative_profit_usdc      - Total profit


🐛 TROUBLESHOOTING
===================

Problem: Module not found (pandas, matplotlib, etc.)
Solution: pip install -r tools/requirements-analysis.txt

Problem: File not found
Solution: Use full path: python tools/visualize_performance.py /full/path/to/file.csv

Problem: CSV missing columns
Solution: Verify using correct file: logs/markets/{date}/market_performance.csv

Problem: Script won't run on Windows with bash
Solution: Use visualize.bat instead


📚 DOCUMENTATION
=================

File                            Purpose
────────────────────────────────────────────────────────────
tools/README.md                 Complete documentation
tools/VISUALIZATION_QUICKSTART.md  Quick reference
tools/INDEX.md                  Directory index
tools/example_usage.py          Code examples
tools/QUICK_REFERENCE.py        This file


⏱️ TYPICAL EXECUTION TIME
=========================

Small dataset (1-10 trades):   < 1 second
Medium dataset (10-100 trades): 1-2 seconds
Large dataset (100+ trades):   2-5 seconds


💾 OUTPUT SIZE
==============

Per chart:    300 KB - 1.5 MB
All 6 charts: 2-5 MB
Resolution:  300 DPI (print quality)


✨ KEY FEATURES
================

✅ Professional 300 DPI PNG output
✅ 6 different chart types
✅ Color coded (green/red)
✅ Works on Windows/Mac/Linux
✅ Simple command-line interface
✅ Python module support
✅ Fast processing
✅ Comprehensive analysis
✅ Automatic directory creation
✅ Clear error messages


🎨 CHART DESCRIPTIONS
======================

01_profit_timeline.png
  Top: Individual trade profits (bar chart)
  Bottom: Cumulative profit trend (line chart)
  → Use to see profit/loss progression over time

02_win_rate_analysis.png
  1. Win rate over time (line chart)
  2. Total wins vs losses (bar chart)
  3. Positions per trade (bar chart)
  4. Profit % per trade (bar chart)
  → Use to analyze trading performance metrics

03_price_analysis.png
  1. Entry vs exit prices (bar chart)
  2. Price spread analysis (bar chart)
  3. Entry price distribution (histogram)
  4. Entry price vs profit (scatter plot)
  → Use to analyze pricing and entry strategies

04_fee_analysis.png
  1. Gross vs net profit (bar chart)
  2. Fees per trade (bar chart)
  3. Fee % of gross profit (bar chart)
  4. Cumulative fees trend (line chart)
  → Use to analyze fee impact

05_account_balance.png
  Single chart showing account balance progression
  → Use to track overall account growth

06_summary_stats.png
  Dashboard with:
  - Key statistics summary
  - Top 3 best trades
  - Worst 3 trades
  - Win/loss pie chart
  - Hourly profit breakdown
  → Use for quick overview and metrics


🔄 BATCH PROCESSING
====================

Process all CSV files:
───────────────────────
for csv in logs/markets/*/market_performance.csv; do
    python tools/visualize_performance.py "$csv"
done

Process specific date range:
────────────────────────────
for csv in logs/markets/2026-04-2[0-3]*/market_performance.csv; do
    python tools/visualize_performance.py "$csv" -o charts/$(basename $(dirname "$csv"))
done


🎯 NEXT STEPS
=============

1. Install: pip install -r tools/requirements-analysis.txt
2. Find CSV: logs/markets/{date_time}/market_performance.csv
3. Run: python tools/visualize_performance.py <csv_file>
4. View: Open generated PNG files
5. Analyze: Look for patterns and insights
6. Improve: Update strategy based on data


📞 HELP
=======

CLI help:
  python tools/visualize_performance.py --help

Full documentation:
  tools/README.md

Quick reference:
  tools/VISUALIZATION_QUICKSTART.md

Code examples:
  tools/example_usage.py

Tool index:
  tools/INDEX.md

This file:
  tools/QUICK_REFERENCE.py (just print it!)


✨ REMEMBER ✨
==============

→ Always use the correct CSV file from logs/markets/
→ Install dependencies first (pip install -r...)
→ Charts are saved as PNG files in ./charts/
→ No data is modified or uploaded anywhere
→ All analysis is local to your machine


═══════════════════════════════════════════════════════════════════════════════

Good luck with your analysis! 🚀📊

═══════════════════════════════════════════════════════════════════════════════
"""

if __name__ == "__main__":
    print(QUICK_START)
