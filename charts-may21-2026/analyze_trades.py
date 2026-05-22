#!/usr/bin/env python3
"""
Trade Analysis and Visualization Script for Polymarket Export Data

Analyzes Buy/Redeem transactions and generates performance visualizations.
Accounts for redeems that represent closed positions (no corresponding buy = asset went to 0).
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime
from pathlib import Path
import numpy as np
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Load data
csv_file = Path("market_export.csv")
df = pd.read_csv(csv_file)

# Convert timestamp to datetime
df['datetime'] = pd.to_datetime(df['timestamp'].astype(int), unit='s')
df = df.sort_values('datetime')

print(f"\n📊 Trade Analysis Report")
print(f"{'='*60}")
print(f"Total transactions: {len(df)}")
print(f"Date range: {df['datetime'].min()} to {df['datetime'].max()}")
print(f"Unique markets: {df['marketName'].nunique()}")

# Calculate account change over time (P&L + Deposits)
# Track deposits separately to show account inflows
# Group by market time windows (embedded in market name)

def extract_market_time(market_name):
    """Extract time window from market name e.g., 'Bitcoin Up or Down - May 21, 2:30AM-2:35AM ET'"""
    parts = market_name.split(' - ')
    if len(parts) > 1:
        time_part = parts[1].replace(' ET', '').strip('"')
        return time_part
    return market_name

# Initialize counters
buy_count = 0
sell_count = 0
deposit_count = 0
total_deposits = 0
total_bought = 0
total_redeemed = 0

# Build timeline by market time window
account_change_by_market_time = defaultdict(float)
market_time_order = []  # Keep order of market times

for idx, row in df.iterrows():
    amount = float(row['usdcAmount'])
    action = row['action']
    market = row['marketName']
    market_time = extract_market_time(market)
    
    if market_time not in account_change_by_market_time:
        market_time_order.append(market_time)
    
    if action == "Buy":
        account_change_by_market_time[market_time] -= amount
        buy_count += 1
        total_bought += amount
    elif action == "Redeem":
        account_change_by_market_time[market_time] += amount
        sell_count += 1
        total_redeemed += amount
    elif action == "Deposit":
        account_change_by_market_time[market_time] += amount
        deposit_count += 1
        total_deposits += amount

# Build cumulative account changes
account_changes = []
market_times_x_axis = []
cumulative_change = 0
for market_time in market_time_order:
    cumulative_change += account_change_by_market_time[market_time]
    account_changes.append(cumulative_change)
    market_times_x_axis.append(market_time)

# Also keep original timestamps for reference in other calculations
account_change = 0
account_changes_by_transaction = []
timestamps = []
profitable_trades = 0
losing_trades = 0
entry_price_profit_pairs = []  # Track (entry_price_in_tokens, profit_in_usdc) pairs

# Parse market names to understand timing windows
market_windows = defaultdict(lambda: {"buys": [], "redeems": [], "deposits": []})

for idx, row in df.iterrows():
    timestamp = row['datetime']
    amount = float(row['usdcAmount'])
    action = row['action']
    market = row['marketName']
    token_amount = float(row['tokenAmount'])
    
    if action == "Buy":
        account_change -= amount  # Buying costs USDC (reduces account change)
        buy_count += 1
        total_bought += amount
        market_windows[market]["buys"].append({
            'time': timestamp,
            'amount': amount,
            'token_amount': token_amount,
            'token_name': row['tokenName']
        })
    elif action == "Redeem":
        account_change += amount  # Redeeming gets USDC back (increases account change)
        sell_count += 1
        total_redeemed += amount
        market_windows[market]["redeems"].append({
            'time': timestamp,
            'amount': amount,
            'token_amount': token_amount
        })
    elif action == "Deposit":
        account_change += amount  # Deposits increase account change
        deposit_count += 1
        total_deposits += amount
        market_windows[market]["deposits"].append({
            'time': timestamp,
            'amount': amount
        })
    
    account_changes_by_transaction.append(account_change)
    timestamps.append(timestamp)

# Calculate P&L and Total Account Change
pnl = total_redeemed - total_bought
total_account_change = pnl + total_deposits

print(f"\n💰 Account Change Summary")
print(f"{'='*60}")
print(f"Total deposits: ${total_deposits:.2f}")
print(f"P&L from trading: ${pnl:.4f}")
print(f"Total account change: ${total_account_change:.4f}")

# Buy/Sell analysis
print(f"\n📈 Trade Statistics")
print(f"{'='*60}")
print(f"Total buys: {buy_count} (${total_bought:.2f})")
print(f"Total redeems: {sell_count} (${total_redeemed:.2f})")
print(f"Total deposits: {deposit_count} (${total_deposits:.2f})")
print(f"Avg buy size: ${total_bought/buy_count:.4f}" if buy_count > 0 else "N/A")
print(f"Avg redeem size: ${total_redeemed/sell_count:.4f}" if sell_count > 0 else "N/A")

# Calculate win rate - match multiple buys per market to redeems
# Each redeem can cover multiple buys; buys without a redeem are liquidations (losses)
win_count = 0
loss_count = 0
for market, data in market_windows.items():
    buys = data["buys"]
    redeems = data["redeems"]
    
    # Track cumulative amounts
    total_buy_amount = sum(b['amount'] for b in buys)
    total_redeem_amount = sum(r['amount'] for r in redeems)
    total_buy_tokens = sum(b['token_amount'] for b in buys)
    
    if total_buy_amount > 0:
        if total_redeem_amount > 0:
            # There were redeems for this market - those buys were closed
            # Calculate average entry price
            avg_entry_price = total_buy_amount / total_buy_tokens if total_buy_tokens > 0 else 0
            
            # Calculate exit price from redeem
            total_redeem_tokens = sum(r['token_amount'] for r in redeems)
            avg_exit_price = total_redeem_amount / total_redeem_tokens if total_redeem_tokens > 0 else 0
            
            # Distribute profit across all buys that were redeemed
            profit_per_token = avg_exit_price - avg_entry_price
            
            for buy in buys:
                # Each buy participated in the redeem
                buy_entry_price = buy['amount'] / buy['token_amount'] if buy['token_amount'] > 0 else 0
                # Profit based on the market's average exit price vs this buy's entry price
                profit = (avg_exit_price - buy_entry_price) * buy['token_amount']
                
                win_count += 1
                entry_price_profit_pairs.append({
                    'entry_price': buy_entry_price,
                    'profit': profit,  # Individual buy's profit based on entry and market exit
                    'tokens': buy['token_amount']
                })
        else:
            # No redeems for this market - all buys are liquidated losses
            for buy in buys:
                loss_count += 1
                entry_price_profit_pairs.append({
                    'entry_price': buy['amount'] / buy['token_amount'] if buy['token_amount'] > 0 else 0,
                    'profit': -buy['amount'],  # Total loss
                    'tokens': buy['token_amount']
                })

total_closed_trades = win_count + loss_count
win_rate = (win_count / total_closed_trades * 100) if total_closed_trades > 0 else 0
print(f"Win rate: {win_rate:.1f}% ({win_count}W / {loss_count}L from liquidations)")
print(f"Total closed trades: {total_closed_trades}")

# Market-by-market analysis
print(f"\n🎯 Market Performance")
print(f"{'='*60}")
market_summary = []
for market, data in sorted(market_windows.items()):
    buys = data["buys"]
    redeems = data["redeems"]
    
    buy_vol = sum(b['amount'] for b in buys)
    redeem_vol = sum(r['amount'] for r in redeems)
    
    if buy_vol > 0:
        pnl = redeem_vol - buy_vol
        pnl_pct = (pnl / buy_vol) * 100 if buy_vol > 0 else 0
        
        market_summary.append({
            'market': market,
            'buys': len(buys),
            'redeems': len(redeems),
            'buy_vol': buy_vol,
            'redeem_vol': redeem_vol,
            'pnl': pnl,
            'pnl_pct': pnl_pct
        })

market_df = pd.DataFrame(market_summary)
if not market_df.empty:
    market_df = market_df.sort_values('pnl', ascending=False)
    print(f"\n{'Market':<50} {'Trades':<10} {'P&L':>10} {'%':>7}")
    print(f"{'-'*80}")
    for _, row in market_df.head(10).iterrows():
        trades = f"{int(row['buys'])}/{int(row['redeems'])}"
        print(f"{row['market']:<50} {trades:<10} ${row['pnl']:>9.2f} {row['pnl_pct']:>6.1f}%")

# Track major loss events by market with timestamps
market_loss_events = []  # List of (timestamp, market_name, loss_amount)
for market, data in market_windows.items():
    buys = data["buys"]
    redeems = data["redeems"]
    
    total_buy_amount = sum(b['amount'] for b in buys)
    total_redeem_amount = sum(r['amount'] for r in redeems)
    
    if total_buy_amount > 0:
        loss = total_redeem_amount - total_buy_amount
        if loss < 0:  # Actual loss on this market (includes liquidations with 0 redeems)
            # Get the earliest buy time for this market
            earliest_time = min(b['time'] for b in buys)
            market_loss_events.append({
                'time': earliest_time,
                'market': market,
                'loss': loss,
                'abs_loss': abs(loss)
            })

# Sort by absolute loss magnitude and get top 5 major losses
market_loss_events_sorted = sorted(market_loss_events, key=lambda x: x['abs_loss'], reverse=True)
major_losses = market_loss_events_sorted[:5]

# Generate visualizations
fig = plt.figure(figsize=(16, 12))
gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)

# 1. Account Change Over Time (P&L + Deposits) - By Market Time
ax1 = fig.add_subplot(gs[0, :])
ax1.plot(range(len(market_times_x_axis)), account_changes, linewidth=2, color='#2E86AB', label='Account Change', marker='o', markersize=4)
ax1.fill_between(range(len(market_times_x_axis)), 0, account_changes, alpha=0.3, color='#2E86AB')
ax1.axhline(y=0, color='gray', linestyle='--', alpha=0.5, linewidth=1)
ax1.axhline(y=total_deposits, color='green', linestyle='--', alpha=0.5, linewidth=1, label=f'Total Deposits: ${total_deposits:.2f}')

ax1.set_xticks(range(0, len(market_times_x_axis), max(1, len(market_times_x_axis)//10)))
ax1.set_xticklabels([market_times_x_axis[i] for i in range(0, len(market_times_x_axis), max(1, len(market_times_x_axis)//10))], rotation=45, ha='right', fontsize=8)
ax1.set_ylabel('Account Change (USDC)', fontsize=12, fontweight='bold')
ax1.set_title('Account Change Over Time (P&L + Deposits) - By Market Time Window', fontsize=14, fontweight='bold')
ax1.legend(loc='best')
ax1.grid(True, alpha=0.3)

# Annotate major loss points on the graph
for loss_event in major_losses:
    # Find the market time that matches this loss
    market_time = extract_market_time(loss_event['market'])
    try:
        idx = market_times_x_axis.index(market_time)
        ax1.scatter(idx, account_changes[idx], color='red', s=200, marker='X', zorder=5, edgecolors='darkred', linewidth=2)
        
        label_text = f"{market_time}\n${loss_event['loss']:.2f}"
        ax1.annotate(label_text, 
                    xy=(idx, account_changes[idx]),
                    xytext=(0, -50),
                    textcoords='offset points',
                    ha='center',
                    fontsize=8,
                    bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7),
                    arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0', color='red', lw=1.5))
    except ValueError:
        pass  # Market time not found

# Annotate deposit points on the graph
for market, data in market_windows.items():
    deposits = data["deposits"]
    if deposits:
        market_time = extract_market_time(market)
        try:
            idx = market_times_x_axis.index(market_time)
            total_deposit_amount = sum(d['amount'] for d in deposits)
            ax1.scatter(idx, account_changes[idx], color='green', s=150, marker='^', zorder=5, edgecolors='darkgreen', linewidth=2)
            
            label_text = f"Deposit\n${total_deposit_amount:.2f}"
            ax1.annotate(label_text, 
                        xy=(idx, account_changes[idx]),
                        xytext=(0, 30),
                        textcoords='offset points',
                        ha='center',
                        fontsize=8,
                        bbox=dict(boxstyle='round,pad=0.5', facecolor='lightgreen', alpha=0.7),
                        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0', color='green', lw=1.5))
        except ValueError:
            pass  # Market time not found

# 2. Win Rate Statistics (Pie Chart)
ax2 = fig.add_subplot(gs[1, 0])
win_loss_data = [win_count, loss_count]
colors_pie = ['#06A77D', '#E63946']
wedges, texts, autotexts = ax2.pie(win_loss_data, labels=[f'Wins\n({win_count})', f'Losses\n({loss_count})'], 
                                     autopct='%1.1f%%', colors=colors_pie, startangle=90, textprops={'fontsize': 11, 'fontweight': 'bold'})
ax2.set_title(f'Win Rate: {win_rate:.1f}%', fontsize=12, fontweight='bold')

# 3. Account Change Over Time (Dollar Amount) - By Market Time
ax3 = fig.add_subplot(gs[1, 1])
ax3.plot(range(len(market_times_x_axis)), account_changes, linewidth=2, color='#A23B72', marker='o', markersize=4)
ax3.fill_between(range(len(market_times_x_axis)), 0, account_changes, alpha=0.3, color='#A23B72')
ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

# Annotate major loss points on this chart too
for loss_event in major_losses:
    market_time = extract_market_time(loss_event['market'])
    try:
        idx = market_times_x_axis.index(market_time)
        ax3.scatter(idx, account_changes[idx], color='red', s=150, marker='X', zorder=5, edgecolors='darkred', linewidth=1.5)
    except ValueError:
        pass

ax3.set_xticks(range(0, len(market_times_x_axis), max(1, len(market_times_x_axis)//10)))
ax3.set_xticklabels([market_times_x_axis[i] for i in range(0, len(market_times_x_axis), max(1, len(market_times_x_axis)//10))], rotation=45, ha='right', fontsize=8)
ax3.set_ylabel('Account Change ($)', fontsize=11, fontweight='bold')
ax3.set_title('Cumulative Account Change Over Time (By Market Time)', fontsize=12, fontweight='bold')
ax3.grid(True, alpha=0.3)

# 4. Entry Price vs Profit Scatter Plot
ax4 = fig.add_subplot(gs[2, 0])
if entry_price_profit_pairs:
    entry_prices = [p['entry_price'] for p in entry_price_profit_pairs]
    profits = [p['profit'] for p in entry_price_profit_pairs]
    colors_scatter = ['#06A77D' if p > 0 else '#E63946' for p in profits]
    
    ax4.scatter(entry_prices, profits, alpha=0.6, s=80, c=colors_scatter, edgecolors='black', linewidth=0.5)
    ax4.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    ax4.set_xlabel('Entry Price (USDC/Token)', fontsize=11, fontweight='bold')
    ax4.set_ylabel('Profit/Loss (USDC)', fontsize=11, fontweight='bold')
    ax4.set_title('Entry Price vs Profit Distribution', fontsize=12, fontweight='bold')
    ax4.grid(True, alpha=0.3)

# 5. Market Performance Summary
ax5 = fig.add_subplot(gs[2, 1])
if not market_df.empty:
    top_markets = market_df.head(8)
    colors_market = ['green' if x > 0 else 'red' for x in top_markets['pnl']]
    ax5.barh(range(len(top_markets)), top_markets['pnl'].values, color=colors_market, alpha=0.7)
    ax5.set_yticks(range(len(top_markets)))
    ax5.set_yticklabels([m.split(' - ')[1] if ' - ' in m else m for m in top_markets['market'].values], fontsize=9)
    ax5.set_xlabel('P&L (USDC)', fontsize=11, fontweight='bold')
    ax5.set_title('Top Markets by P&L', fontsize=12, fontweight='bold')
    ax5.axvline(x=0, color='black', linestyle='-', linewidth=0.5)
    ax5.grid(True, alpha=0.3, axis='x')
    
    # Add value labels
    for i, v in enumerate(top_markets['pnl'].values):
        ax5.text(v, i, f' ${v:.2f}', va='center', fontweight='bold', fontsize=9)

plt.suptitle('🤖 Janus Trading Bot - May 20, 2026 Performance Analysis', 
             fontsize=16, fontweight='bold', y=0.995)

# Display the figure in a Python application window
print("\n📊 Displaying visualization... (close the window to continue)")
plt.show()

# Save figure after displaying
output_file = Path("trading_analysis.png")
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f"✅ Visualization saved: {output_file}")

# Additional Stats Export
stats_file = Path("trading_stats.txt")
with open(stats_file, 'w') as f:
    f.write("JANUS TRADING BOT - PERFORMANCE SUMMARY\n")
    f.write("="*60 + "\n\n")
    f.write(f"Analysis Date: May 20-21, 2026\n")
    f.write(f"Time Range: {df['datetime'].min().strftime('%Y-%m-%d %H:%M:%S')} to {df['datetime'].max().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    f.write(f"ACCOUNT CHANGE SUMMARY\n")
    f.write(f"-"*60 + "\n")
    f.write(f"Total Deposits: ${total_deposits:.2f}\n")
    f.write(f"Trading P&L: ${pnl:.4f}\n")
    f.write(f"Total Account Change: ${total_account_change:.4f}\n\n")
    f.write(f"TRADE STATISTICS\n")
    f.write(f"-"*60 + "\n")
    f.write(f"Total Buy Orders: {buy_count}\n")
    f.write(f"Total Redeems: {sell_count}\n")
    f.write(f"Total Deposits: {deposit_count}\n")
    f.write(f"Total USDC Deployed: ${total_bought:.2f}\n")
    f.write(f"Total USDC Recovered: ${total_redeemed:.2f}\n")
    f.write(f"Win Rate: {(total_redeemed > total_bought)*100:.0f}%\n")
    f.write(f"Closed Trades: {total_closed_trades}\n")
    f.write(f"Wins: {win_count} | Losses: {loss_count}\n")
    f.write(f"Trade Win Rate: {win_rate:.1f}%\n\n")
    f.write(f"TOP PERFORMING MARKETS\n")
    f.write(f"-"*60 + "\n")
    for _, row in market_df.head(5).iterrows():
        f.write(f"{row['market']}\n")
        f.write(f"  Buys/Redeems: {int(row['buys'])}/{int(row['redeems'])}\n")
        f.write(f"  P&L: ${row['pnl']:.2f} ({row['pnl_pct']:.1f}%)\n")

print(f"✅ Stats exported: {stats_file}")
