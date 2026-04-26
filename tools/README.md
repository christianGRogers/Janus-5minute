# Janus Bot Tools

This directory contains utility scripts for analyzing and visualizing Janus Bot trading performance.

## 📊 Performance Visualization Tool

`visualize_performance.py` - Generate comprehensive visualizations of trading performance data from CSV log files.

### Features

- **Profit Timeline**: View individual trade profits and cumulative profit trends
- **Win Rate Analysis**: Track win rate over time, total wins vs losses, profit percentages
- **Price Analysis**: Entry/exit price comparison, price distribution, price vs profit correlation
- **Fee Analysis**: Gross vs net profit, fee impact, cumulative fees
- **Account Balance**: Track account balance progression over time
- **Summary Statistics**: Comprehensive dashboard with key metrics and insights
- **Hourly Performance**: Analyze trading performance by hour of day

### Installation

1. Install required packages:
```bash
pip install -r requirements-analysis.txt
```

Or install individually:
```bash
pip install pandas matplotlib seaborn numpy
```

### Usage

#### Basic Usage
```bash
python visualize_performance.py <path_to_csv>
```

#### With Custom Output Directory
```bash
python visualize_performance.py market_performance.csv --output ./my_charts
```

#### Examples
```bash
# From the logs directory
python visualize_performance.py ../logs/markets/2026-04-23_22-15-45/market_performance.csv

# Save to specific location
python visualize_performance.py market_performance.csv -o ~/analysis/charts

# From current directory
python visualize_performance.py ./market_performance.csv
```

### Output

The script generates 6 comprehensive visualization files in the output directory:

1. **01_profit_timeline.png**
   - Bar chart of individual trade profits
   - Cumulative profit trend line
   - Shows profit/loss for each trade

2. **02_win_rate_analysis.png**
   - Win rate trend over time
   - Win vs loss count comparison
   - Positions per trade
   - Profit percentage per trade

3. **03_price_analysis.png**
   - Entry vs exit price comparison
   - Price spread analysis
   - Entry price distribution histogram
   - Entry price vs profit scatter plot

4. **04_fee_analysis.png**
   - Gross vs net profit comparison
   - Individual trade fees
   - Fee percentage of gross profit
   - Cumulative fees over time

5. **05_account_balance.png**
   - Account balance progression
   - Starting balance reference line
   - Balance changes over time

6. **06_summary_stats.png**
   - Key statistics dashboard
   - Top 3 best trades
   - Worst 3 trades
   - Average metrics
   - Win/loss distribution pie chart
   - Hourly profit breakdown

### CSV File Format

The script expects a CSV file with the following columns:

```
timestamp,market_id,window_duration_sec,position_count,correct_positions,wrong_positions,
win_rate_pct,gross_profit_usdc,total_fees_usdc,net_profit_usdc,avg_profit_pct,
avg_entry_price,avg_exit_price,total_size_traded,final_up_price,final_down_price,
resolution,account_balance_usdc,cumulative_profit_usdc
```

Example row:
```
2026-04-23T22:20:00-04:00,btc-updown-5m-1776996900,300,1,0,1,0.00,2.1311,0.1320,1.9991,93.81,0.1400,0.0000,15.22,0.0000,0.9900,DOWN,10004.1302,1.9991
```

### Command-Line Options

```
positional arguments:
  csv_file              Path to market_performance.csv file

optional arguments:
  -h, --help            show this help message and exit
  --output OUTPUT, -o OUTPUT
                        Output directory for charts (default: ./charts)
```

### Troubleshooting

#### File Not Found Error
```
❌ Error: CSV file not found: market_performance.csv
```
**Solution**: Verify the path to your CSV file is correct. Use absolute paths if relative paths don't work.

#### Missing Columns Error
```
❌ Error: CSV is missing required columns: [...]
```
**Solution**: Ensure you're using the correct CSV file from `logs/markets/{date}/market_performance.csv`

#### Import Errors
```
ModuleNotFoundError: No module named 'matplotlib'
```
**Solution**: Install requirements:
```bash
pip install -r requirements-analysis.txt
```

### Performance Tips

- For large datasets (100+ trades), consider opening the PNGs with your system's image viewer rather than a web browser for faster loading
- Charts are saved at 300 DPI for high quality
- All plots use dark grid style for easy reading
- Color coding: Green = Profit/Win, Red = Loss

### Examples

#### Analyze Today's Trading
```bash
# Find the latest log directory
cd logs/markets
ls -t | head -1  # Get the most recent directory

# Run visualization on that directory
cd <most_recent_directory>
python ../../tools/visualize_performance.py market_performance.csv --output ./analysis
```

#### Compare Multiple Days
```bash
# Run for each day's CSV
python tools/visualize_performance.py logs/markets/2026-04-23_22-15-45/market_performance.csv -o charts/2026-04-23
python tools/visualize_performance.py logs/markets/2026-04-24_10-30-00/market_performance.csv -o charts/2026-04-24
```

### Example Output

When successful, you'll see:
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

## Future Tools

More analysis tools can be added to this directory:
- Real-time trading dashboard
- Market sentiment analysis
- Performance comparison tool
- Trade optimization analyzer

## License

See main repository LICENSE file.
