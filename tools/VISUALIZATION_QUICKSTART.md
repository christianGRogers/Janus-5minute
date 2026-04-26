# 📊 Janus Bot Visualization Tools - Quick Start

## What's New

I've created a complete performance visualization toolkit in the `tools/` folder that generates comprehensive charts from your trading logs.

## Files Added

- **`visualize_performance.py`** - Main visualization tool (Python)
- **`visualize.sh`** - Quick start script for Linux/macOS
- **`visualize.bat`** - Quick start script for Windows
- **`__init__.py`** - Makes tools a Python package
- **`requirements-analysis.txt`** - Python dependencies
- **`README.md`** - Complete documentation

## Quick Start

### On Linux/macOS

```bash
cd tools
bash visualize.sh ../logs/markets/2026-04-23_22-15-45/market_performance.csv
```

### On Windows

```cmd
cd tools
visualize.bat ..\logs\markets\2026-04-23_22-15-45\market_performance.csv
```

### Direct Python Usage

```bash
python visualize_performance.py market_performance.csv --output ./charts
```

## Installation

```bash
pip install -r tools/requirements-analysis.txt
```

## Generated Visualizations

The tool generates **6 comprehensive charts**:

### 1. **Profit Timeline** (`01_profit_timeline.png`)
- Individual trade profits (bar chart)
- Cumulative profit trend (line chart)
- Shows profit/loss for each trade over time

### 2. **Win Rate Analysis** (`02_win_rate_analysis.png`)
- Win rate trend over time
- Win vs loss count (bar chart)
- Positions per trade
- Profit percentage per trade

### 3. **Price Analysis** (`03_price_analysis.png`)
- Entry vs exit price comparison
- Price spread analysis (Entry - Exit)
- Entry price distribution (histogram)
- Entry price vs profit correlation (scatter)

### 4. **Fee Analysis** (`04_fee_analysis.png`)
- Gross vs net profit comparison
- Individual trade fees
- Fee percentage of gross profit
- Cumulative fees over time

### 5. **Account Balance** (`05_account_balance.png`)
- Account balance progression
- Starting balance reference line
- Shows balance growth/decline over time

### 6. **Summary Statistics** (`06_summary_stats.png`)
- Key metrics dashboard
- Top 3 best trades
- Worst 3 trades
- Average entry/exit prices
- Win/loss distribution pie chart
- Hourly profit breakdown

## Features

✅ **Professional Charts** - High quality 300 DPI output
✅ **Color Coded** - Green for profits, red for losses
✅ **Easy to Use** - Simple command-line interface
✅ **Cross-Platform** - Works on Windows, macOS, Linux
✅ **Comprehensive** - Analyzes all aspects of trading performance
✅ **Smart Defaults** - Auto-creates output directories

## Usage Examples

### Example 1: Basic Usage
```bash
python visualize_performance.py market_performance.csv
# Output saved to ./charts/
```

### Example 2: Custom Output Directory
```bash
python visualize_performance.py market_performance.csv --output ~/Desktop/analysis
# Output saved to ~/Desktop/analysis/
```

### Example 3: From Your Log Directory
```bash
cd logs/markets/2026-04-23_22-15-45
python ../../tools/visualize_performance.py market_performance.csv
```

### Example 4: Using the Bash Script
```bash
cd tools
bash visualize.sh ../logs/markets/2026-04-23_22-15-45/market_performance.csv --output ./results
```

### Example 5: Using the Batch Script (Windows)
```cmd
cd tools
visualize.bat ..\logs\markets\2026-04-23_22-15-45\market_performance.csv .\results
```

## Data Analysis Capabilities

The visualization tool analyzes:

- **Profitability**: Net profit, gross profit, fees, ROI
- **Win Rate**: Winning percentage, win vs loss ratio
- **Trading Activity**: Position sizes, trade counts, hourly distribution
- **Price Dynamics**: Entry/exit prices, spreads, price distributions
- **Fee Impact**: Fee percentage, cumulative fees, fee trends
- **Account Performance**: Balance progression, growth rate

## Output Example

When you run the tool, you'll see:

```
✅ Loaded 7 trades from market_performance.csv

📊 Generating visualization charts...

1. Plotting profit timeline...
📊 Saved: /path/to/charts/01_profit_timeline.png
2. Plotting win rate analysis...
📊 Saved: /path/to/charts/02_win_rate_analysis.png
3. Plotting price analysis...
📊 Saved: /path/to/charts/03_price_analysis.png
4. Plotting fee analysis...
📊 Saved: /path/to/charts/04_fee_analysis.png
5. Plotting account balance...
📊 Saved: /path/to/charts/05_account_balance.png
6. Plotting summary statistics...
📊 Saved: /path/to/charts/06_summary_stats.png

✅ All charts generated successfully!
📁 Output directory: /path/to/charts
```

## Viewing Results

All output PNG files can be opened with:
- Windows: Preview, Paint, or any web browser
- macOS: Preview
- Linux: GIMP, Eog (Eye of GNOME), or any image viewer

The scripts automatically attempt to open the output directory when complete.

## Requirements

- Python 3.6+
- pandas
- matplotlib
- seaborn
- numpy

All automatically installed via `pip install -r requirements-analysis.txt`

## Troubleshooting

### "File not found" error
```bash
# Make sure the path to CSV is correct
# Use full paths if relative paths don't work
python visualize_performance.py /full/path/to/market_performance.csv
```

### "Module not found" error
```bash
# Install requirements
pip install -r requirements-analysis.txt
```

### Can't run bash script on Windows
```cmd
# Use the batch file instead
visualize.bat market_performance.csv
```

## Advanced Usage

### As a Python Module

```python
from tools.visualize_performance import BotPerformanceVisualizer

# Create visualizer
viz = BotPerformanceVisualizer('market_performance.csv', output_dir='./output')

# Generate all charts
viz.generate_all_charts()

# Or generate specific charts
viz.plot_profit_timeline()
viz.plot_win_rate_analysis()
viz.plot_price_analysis()
```

### Batch Processing Multiple Days

```bash
for csv in logs/markets/*/market_performance.csv; do
    dir=$(dirname "$csv")
    date=$(basename "$dir")
    python tools/visualize_performance.py "$csv" --output "charts/$date"
done
```

## Next Steps

1. **Generate charts** for your recent trades
2. **Analyze patterns** in the visualizations
3. **Identify improvements** based on data
4. **Update strategy** based on insights
5. **Monitor performance** over time

## Tips

- Generate charts regularly to track performance trends
- Look for patterns in entry prices and win rates
- Check if fees are eating too much into profits
- Analyze hourly performance to find best trading hours
- Use account balance progression to verify growth

---

Happy analyzing! 📊✨
