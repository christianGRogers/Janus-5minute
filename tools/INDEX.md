# Janus Bot Tools Directory

Complete toolkit for analyzing and visualizing Janus Bot trading performance.

## 📁 Contents

### Core Visualization Tool
- **`visualize_performance.py`** - Main Python visualization engine
  - Generates 6 comprehensive performance charts
  - Analyzes profit, win rate, prices, fees, and account balance
  - 500+ lines of professional-grade analysis code

### Quick Start Scripts
- **`visualize.sh`** - Linux/macOS quick start (bash script)
- **`visualize.bat`** - Windows quick start (batch script)
- **`example_usage.py`** - Python usage examples

### Documentation
- **`README.md`** - Complete tool documentation
- **`VISUALIZATION_QUICKSTART.md`** - Quick reference guide
- **`requirements-analysis.txt`** - Python dependencies

### Package Files
- **`__init__.py`** - Python package initialization
- **`analyze_performance.py`** - Legacy analysis tool (kept for reference)

## 🚀 Quick Start

### Install Dependencies
```bash
pip install -r requirements-analysis.txt
```

### Run Visualization

#### Linux/macOS
```bash
bash visualize.sh <csv_file>
```

#### Windows
```cmd
visualize.bat <csv_file>
```

#### Direct Python
```bash
python visualize_performance.py <csv_file>
```

## 📊 Generated Visualizations

The main visualization tool creates 6 PNG charts:

1. **01_profit_timeline.png** - Individual and cumulative profits
2. **02_win_rate_analysis.png** - Win rate trends and distribution
3. **03_price_analysis.png** - Entry/exit price analysis
4. **04_fee_analysis.png** - Fee impact and analysis
5. **05_account_balance.png** - Account balance progression
6. **06_summary_stats.png** - Dashboard with key metrics

## 💾 Data Source

Expects CSV format from: `logs/markets/{timestamp}/market_performance.csv`

Example:
```
logs/markets/2026-04-23_22-15-45/market_performance.csv
```

## 🎯 Key Features

✅ Professional 300 DPI charts
✅ Color-coded analysis (green/red)
✅ Cross-platform (Windows/Mac/Linux)
✅ Easy command-line interface
✅ Python module support
✅ Comprehensive statistics
✅ Customizable output directory

## 📖 Usage Examples

### Basic
```bash
python visualize_performance.py market_performance.csv
```

### With Output Directory
```bash
python visualize_performance.py market_performance.csv --output ~/analysis
```

### From Current Directory
```bash
cd tools
bash visualize.sh ../logs/markets/2026-04-23_22-15-45/market_performance.csv
```

### Batch Processing
```bash
for csv in logs/markets/*/market_performance.csv; do
    python tools/visualize_performance.py "$csv"
done
```

## 🔧 Advanced Usage

### As Python Module
```python
from visualize_performance import BotPerformanceVisualizer

viz = BotPerformanceVisualizer('market_performance.csv')
viz.generate_all_charts()

# Or customize
viz.plot_profit_timeline()
viz.plot_win_rate_analysis()
```

### Direct Data Access
```python
from visualize_performance import BotPerformanceVisualizer

viz = BotPerformanceVisualizer('market_performance.csv')
df = viz.df

# Your custom analysis here
print(df.describe())
print(df['net_profit_usdc'].sum())
```

## 📋 Requirements

- Python 3.6+
- pandas >= 1.5.0
- matplotlib >= 3.6.0
- seaborn >= 0.12.0
- numpy >= 1.23.0

## 🐛 Troubleshooting

### Module Not Found
```bash
pip install -r requirements-analysis.txt
```

### File Not Found
```bash
# Use absolute path
python visualize_performance.py /full/path/to/market_performance.csv
```

### CSV Missing Columns
- Verify you're using the correct CSV file
- File should be `market_performance.csv` (not JSONL)
- Check file path and format

## 📚 Documentation

- **Full Documentation**: See `README.md`
- **Quick Reference**: See `VISUALIZATION_QUICKSTART.md`
- **Code Examples**: See `example_usage.py`
- **Help**: `python visualize_performance.py --help`

## 🔄 Workflow Integration

### Daily Analysis
```bash
# After trading session ends
python tools/visualize_performance.py logs/markets/$(date +%Y-%m-%d_%H-%M-%S)/market_performance.csv
```

### Scheduled Analysis (Cron)
```bash
# Add to crontab to run daily at 2 AM
0 2 * * * cd /path/to/janus-bot && python tools/visualize_performance.py logs/markets/*/market_performance.csv -o ~/charts/$(date +\%Y-\%m-\%d)
```

## 📊 Analysis Covered

- **Profitability Analysis**: Gross/net profit, fees, ROI
- **Win Rate Analysis**: Winning percentage, trade distribution
- **Price Analysis**: Entry/exit analysis, price trends
- **Fee Impact**: Commission analysis, cost trends
- **Account Health**: Balance progression, growth metrics
- **Performance Patterns**: Hourly breakdown, time-based analysis

## 🎨 Customization

Charts can be customized by editing `visualize_performance.py`:
- Modify colors and styles (lines 30-32)
- Adjust chart dimensions (line 31)
- Change number formatting
- Add additional metrics

## 💡 Tips

1. Generate charts regularly to track trends
2. Compare charts across different days
3. Identify patterns in entry prices
4. Monitor fee impact on profitability
5. Use hourly breakdown to find best trading times
6. Share charts with others for analysis

## 📄 CSV Format Reference

Required columns in market_performance.csv:
```
timestamp, market_id, window_duration_sec, position_count, 
correct_positions, wrong_positions, win_rate_pct, 
gross_profit_usdc, total_fees_usdc, net_profit_usdc, 
avg_profit_pct, avg_entry_price, avg_exit_price, 
total_size_traded, final_up_price, final_down_price, 
resolution, account_balance_usdc, cumulative_profit_usdc
```

## 🚀 Next Steps

1. Install dependencies: `pip install -r requirements-analysis.txt`
2. Find a CSV file: `logs/markets/{date}/market_performance.csv`
3. Run visualization: `python visualize_performance.py <csv_file>`
4. View generated PNG files
5. Analyze patterns and improve strategy

## 📞 Support

For issues or questions:
1. Check `README.md` for detailed documentation
2. Review `VISUALIZATION_QUICKSTART.md` for quick answers
3. See `example_usage.py` for code examples
4. Verify CSV file format and path

---

**Created**: April 2026
**Version**: 1.0.0
**Status**: Production Ready ✅
