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

# Calculate balance progression
# Starting balance: sum of all sells (redeems that closed positions)
# Each buy is a debit, each redeem is a credit

balance = 0
balances = []
timestamps = []
buy_count = 0
sell_count = 0
profitable_trades = 0
losing_trades = 0
total_bought = 0
total_redeemed = 0
entry_price_profit_pairs = []  # Track (entry_price_in_tokens, profit_in_usdc) pairs

# Parse market names to understand timing windows
market_windows = defaultdict(lambda: {"buys": [], "redeems": []})

for idx, row in df.iterrows():
    timestamp = row['datetime']
    amount = float(row['usdcAmount'])
    action = row['action']
    market = row['marketName']
    token_amount = float(row['tokenAmount'])
    
    if action == "Buy":
        balance -= amount  # Buying costs USDC
        buy_count += 1
        total_bought += amount
        market_windows[market]["buys"].append({
            'time': timestamp,
            'amount': amount,
            'token_amount': token_amount,
            'token_name': row['tokenName']
        })
    elif action == "Redeem":
        balance += amount  # Redeeming gets USDC back
        sell_count += 1
        total_redeemed += amount
        market_windows[market]["redeems"].append({
            'time': timestamp,
            'amount': amount,
            'token_amount': token_amount
        })
    
    balances.append(balance)
    timestamps.append(timestamp)

# Calculate starting balance
# If we started at 14.68 current and made these trades, work backwards
starting_balance = 14.68
ending_balance = balance + starting_balance

print(f"\n💰 Balance Tracking (assuming current balance: $14.68)")
print(f"{'='*60}")
print(f"Starting balance: ${starting_balance:.4f}")
print(f"Net P&L from trades: ${balance:.4f}")
print(f"Current balance: ${ending_balance:.4f}")
print(f"P&L %: {(balance/starting_balance)*100:.2f}%")

# Buy/Sell analysis
print(f"\n📈 Trade Statistics")
print(f"{'='*60}")
print(f"Total buys: {buy_count} (${total_bought:.2f})")
print(f"Total redeems: {sell_count} (${total_redeemed:.2f})")
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

# Generate visualizations
fig = plt.figure(figsize=(16, 12))
gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)

# 1. Balance Over Time
ax1 = fig.add_subplot(gs[0, :])
adjusted_balances = [starting_balance + b for b in balances]
ax1.plot(timestamps, adjusted_balances, linewidth=2, color='#2E86AB', label='Account Balance')
ax1.fill_between(timestamps, starting_balance, adjusted_balances, alpha=0.3, color='#2E86AB')
ax1.axhline(y=starting_balance, color='gray', linestyle='--', alpha=0.5, label='Starting Balance')
ax1.set_ylabel('USDC Balance', fontsize=12, fontweight='bold')
ax1.set_title('Account Balance Over Time', fontsize=14, fontweight='bold')
ax1.legend(loc='best')
ax1.grid(True, alpha=0.3)
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')

# 2. Win Rate Statistics (Pie Chart)
ax2 = fig.add_subplot(gs[1, 0])
win_loss_data = [win_count, loss_count]
colors_pie = ['#06A77D', '#E63946']
wedges, texts, autotexts = ax2.pie(win_loss_data, labels=[f'Wins\n({win_count})', f'Losses\n({loss_count})'], 
                                     autopct='%1.1f%%', colors=colors_pie, startangle=90, textprops={'fontsize': 11, 'fontweight': 'bold'})
ax2.set_title(f'Win Rate: {win_rate:.1f}%', fontsize=12, fontweight='bold')

# 3. Return Rate Over Time
ax3 = fig.add_subplot(gs[1, 1])
return_rates = [(b / starting_balance * 100) for b in balances]
colors_line = ['#06A77D' if r >= 0 else '#E63946' for r in return_rates]
ax3.plot(timestamps, return_rates, linewidth=2, color='#A23B72', marker='o', markersize=3)
ax3.fill_between(timestamps, 0, return_rates, alpha=0.3, color='#A23B72')
ax3.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
ax3.set_ylabel('Return %', fontsize=11, fontweight='bold')
ax3.set_title('Return Rate Over Time', fontsize=12, fontweight='bold')
ax3.grid(True, alpha=0.3)
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha='right')

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

# Save figure
output_file = Path("trading_analysis.png")
plt.savefig(output_file, dpi=300, bbox_inches='tight')
print(f"\n✅ Visualization saved: {output_file}")

# Additional Stats Export
stats_file = Path("trading_stats.txt")
with open(stats_file, 'w') as f:
    f.write("JANUS TRADING BOT - PERFORMANCE SUMMARY\n")
    f.write("="*60 + "\n\n")
    f.write(f"Analysis Date: May 20, 2026\n")
    f.write(f"Time Range: {df['datetime'].min().strftime('%Y-%m-%d %H:%M:%S')} to {df['datetime'].max().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    f.write(f"BALANCE TRACKING\n")
    f.write(f"-"*60 + "\n")
    f.write(f"Starting Balance: ${starting_balance:.4f}\n")
    f.write(f"Current Balance: ${ending_balance:.4f}\n")
    f.write(f"Net P&L: ${balance:.4f}\n")
    f.write(f"Return: {(balance/starting_balance)*100:.2f}%\n\n")
    f.write(f"TRADE STATISTICS\n")
    f.write(f"-"*60 + "\n")
    f.write(f"Total Buy Orders: {buy_count}\n")
    f.write(f"Total Redeems: {sell_count}\n")
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

plt.show()
