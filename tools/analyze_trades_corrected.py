#!/usr/bin/env python3
"""
Corrected Trading Performance Analysis
- Properly handles unmatched buy orders as losses
- Includes overall profit visualization
- Outputs charts to specified directory
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np
from io import StringIO
from pathlib import Path

def load_data_from_csv(csv_data):
    """Load trading data from CSV string"""
    df = pd.read_csv(StringIO(csv_data))
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df = df.sort_values('timestamp').reset_index(drop=True)
    return df

def calculate_trades_corrected(df):
    """
    Calculate trades with proper handling of unmatched orders.
    An unmatched BUY (no corresponding REDEEM) is counted as a LOSS.
    """
    trades = []
    active_buys = {}  # Track open buy positions by market
    
    for idx, row in df.iterrows():
        market = row['marketName']
        
        if row['action'] == 'Buy':
            # Track the buy
            if market not in active_buys:
                active_buys[market] = []
            active_buys[market].append({
                'entry_time': row['timestamp'],
                'entry_usdc': row['usdcAmount'],
                'entry_tokens': row['tokenAmount'],
                'entry_price': row['usdcAmount'] / row['tokenAmount'] if row['tokenAmount'] > 0 else 0,
                'hash': row['hash']
            })
        
        elif row['action'] == 'Redeem':
            # Match redeem with most recent buy
            if market in active_buys and len(active_buys[market]) > 0:
                buy = active_buys[market].pop(0)  # FIFO
                exit_usdc = row['usdcAmount']
                entry_usdc = buy['entry_usdc']
                pnl = exit_usdc - entry_usdc
                pnl_pct = (pnl / entry_usdc * 100) if entry_usdc > 0 else 0
                
                trades.append({
                    'market': market,
                    'entry_time': buy['entry_time'],
                    'exit_time': row['timestamp'],
                    'entry_usdc': entry_usdc,
                    'entry_price': buy['entry_price'],
                    'exit_usdc': exit_usdc,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'duration_seconds': (row['timestamp'] - buy['entry_time']).total_seconds(),
                    'status': 'COMPLETED'
                })
    
    # Handle unmatched buys as losses
    for market, buys in active_buys.items():
        for buy in buys:
            trades.append({
                'market': market,
                'entry_time': buy['entry_time'],
                'exit_time': None,  # No matching exit
                'entry_usdc': buy['entry_usdc'],
                'entry_price': buy['entry_price'],
                'exit_usdc': 0,  # Assume total loss
                'pnl': -buy['entry_usdc'],  # Full loss
                'pnl_pct': -100.0,
                'duration_seconds': None,
                'status': 'UNMATCHED_BUY'
            })
    
    return pd.DataFrame(trades).sort_values('entry_time').reset_index(drop=True)

def main():
    # Transaction data
    csv_data = """marketName,action,usdcAmount,tokenAmount,tokenName,timestamp,hash
Bitcoin Up or Down - May 19, 5:35PM-5:40PM ET,Redeem,2.13,2.13,,1779226868,0x90df386cfb3429ab8d3a797ce4f8c3719e41bd9c20628e20e8d86f1f7e40272f
Bitcoin Up or Down - May 19, 5:35PM-5:40PM ET,Buy,1.7278499999999999,2.13,Up,1779226769,0xb58b61672e1f3a0534f75e955607173181241d5c49219097d86cf6194b0b8f77
Bitcoin Up or Down - May 19, 5:20PM-5:25PM ET,Redeem,1.79,1.79,,1779225930,0x23bd649e99c465deddbcc606335d2c363aea4a0513cba34e88635ef6df21d647
Bitcoin Up or Down - May 19, 5:20PM-5:25PM ET,Buy,1.7064499999999998,1.79,Up,1779225848,0x8777e64f5e061c659ad296166e9254b1fe8667bce1b9b1178b2131543599b24d
Bitcoin Up or Down - May 19, 5:10PM-5:15PM ET,Redeem,2.04,2.04,,1779225376,0x660118f04c859be3505e5ff8886c7cbc6fb7abea889a4f946f94f36940be01c4
Bitcoin Up or Down - May 19, 5:10PM-5:15PM ET,Buy,1.57644,2.04,Up,1779225248,0x257e1f5b566a960b37cf34010782e1e2a2bdf6b3594641b66c38ea9ebc827847
Bitcoin Up or Down - May 19, 4:50PM-4:55PM ET,Redeem,1.66,1.66,,1779224130,0xf359fb1f910f3b3666b24b87cc71ee06bb24dd024765ecd1c8a73b0f45395165
Bitcoin Up or Down - May 19, 4:50PM-4:55PM ET,Buy,1.64455,1.66,Up,1779224049,0xf85b6a4a275ce273bf645c4bbb92eaefe769ace79a3e6333991d5692b326825e
Bitcoin Up or Down - May 19, 4:45PM-4:50PM ET,Redeem,1.65,1.65,,1779223832,0x59d8a3714f82dea63dad05df4a0f874ba0862744baa77737b7a7267caa1e218d
Bitcoin Up or Down - May 19, 4:45PM-4:50PM ET,Buy,1.6346399999999999,1.65,Up,1779223748,0xf23bccdf19a7f73bc70ebf18cbf41e1b2656aed577d9bb502de9524e7146ccba
Bitcoin Up or Down - May 19, 4:35PM-4:40PM ET,Redeem,1.65,1.65,,1779223249,0x941f6e3f4e069059483795f9150cc4811157fffc50abcd0da88a7af229728223
Bitcoin Up or Down - May 19, 4:35PM-4:40PM ET,Buy,1.6346399999999999,1.65,Up,1779223178,0x39179196cd36d32b55a4a75cb8d33a99115300632821667fad7d9b02ff693a68
Bitcoin Up or Down - May 19, 4:30PM-4:35PM ET,Redeem,1.6,1.6,,1779222931,0xad14d90768dd72295c7a4b4a147312731be2ac18d931695ef9dd601894261c29
Bitcoin Up or Down - May 19, 4:30PM-4:35PM ET,Buy,1.19007,1.6,Up,1779222849,0xa74e04421fd78e3843e959f9e0ca35269d27ea3d22f3fe700ad153e63b429ec0
Bitcoin Up or Down - May 19, 3:50PM-3:55PM ET,Buy,0.8324,1.25,Up,1779220449,0x79578f34c7d08c0e788463a89defd3b21664b7fda9e78e32c87ce021bf285b9c
Bitcoin Up or Down - May 19, 3:30PM-3:35PM ET,Redeem,1.85,1.85,,1779219909,0x95520dbf7565e561ee7ac1af70f75039c39cea9975d5b6333691ffeaf23819d0
Bitcoin Up or Down - May 19, 3:40PM-3:45PM ET,Buy,0.92997,1.99,Up,1779219860,0xb5c0643c08ebdbbc169ca7cde00279c03079080208b03bb1bd955bff3dda675c
Bitcoin Up or Down - May 19, 3:30PM-3:35PM ET,Buy,1.79826,1.85,Up,1779219249,0x4a22aa7c0e984f18029eb242c18b149ea2c1ca2493648bd67ec6c044f926f87c
Bitcoin Up or Down - May 19, 2:45PM-2:50PM ET,Redeem,1.82,1.82,,1779216631,0x4ecb2b4850609d73b55f834478a94ae146302dfda72f08ad4d52067c25176d20
Bitcoin Up or Down - May 19, 2:45PM-2:50PM ET,Buy,1.7860900000000002,1.82,Up,1779216549,0xd32c8c88c1ff79ea1552c0341f119b5dd459b43206d616897bf7e08ee111956e
Bitcoin Up or Down - May 19, 12:45PM-12:50PM ET,Buy,1.16905,2.35,Up,1779209389,0xb0b198be40412c9ccc3fa0b5743e7108e5d4189ed019bfdf00fd10344dd30b64
Bitcoin Up or Down - May 19, 12:40PM-12:45PM ET,Redeem,1.96,1.96,,1779209132,0x4446036705ebf6a06fd5c8e0596486dca4d6c9ce164f94d55afd0d0e61eb8536
Bitcoin Up or Down - May 19, 12:40PM-12:45PM ET,Buy,1.92348,1.96,Up,1779209048,0xeeb40563e5d54253dd566a18539762ec106415b33fc4d40b3ab4b76194fd6cf6
Bitcoin Up or Down - May 19, 12:00PM-12:05PM ET,Redeem,2.11,2.11,,1779206740,0x49f8d42ead76cfb4fcf13d3adb57d106200a49dd47fab6dab55b7c7f7df3be6a
Bitcoin Up or Down - May 19, 12:00PM-12:05PM ET,Buy,1.58981,2.11,Up,1779206649,0x92bf57ecfebb9957b8213e9f80d3ec976d6e075679dd016ba2d37ea7ab081e18
Bitcoin Up or Down - May 19, 11:55AM-12:00PM ET,Redeem,2.16,2.16,,1779206441,0xd4077be10f233358405bffb2755d2cf75148621887d62b24ade5203d721682bf
Bitcoin Up or Down - May 19, 11:55AM-12:00PM ET,Buy,1.58568,2.16,Up,1779206385,0x30735f86b3147d84d06fd894a82e399523a57920a6bc875fdf6752d58577c5af
Bitcoin Up or Down - May 19, 11:50AM-11:55AM ET,Redeem,2.08,2.08,,1779206129,0x59cf311453c420df8dfcbf15c6f6e73febc4866fb850b1ca5a7c849724d2795f
Bitcoin Up or Down - May 19, 11:50AM-11:55AM ET,Buy,1.72709,2.08,Up,1779206049,0x66fe568d681903a50f679b0f3c2b22b09942280c244c48ee971b2514197114c8
Bitcoin Up or Down - May 19, 11:05AM-11:10AM ET,Buy,0.95951,2.42,Up,1779203394,0x670eb3f3b26df8e258dbec620177782c58ea91f7bec25e127db9e03b54d7c196
Bitcoin Up or Down - May 19, 10:40AM-10:45AM ET,Buy,2.01175,2.67,Up,1779201854,0xecc6b2e3ceee3607cd1a11f1035927f6f57e38acd161bfde287b68a725962606
Bitcoin Up or Down - May 19, 9:10AM-9:15AM ET,Buy,1.35442,2.52,Up,1779196448,0x5ef1c5ec0a1614547eb13e30632195de12fa99088cea5618126356a749033d8c
Bitcoin Up or Down - May 19, 8:45AM-8:50AM ET,Redeem,2.33,2.33,,1779195032,0x9f66da04219f8fa5c88f098ee2b466061aba485484986a1b5a6c1a141364ae9d
Bitcoin Up or Down - May 19, 8:45AM-8:50AM ET,Buy,2.0896600000000003,2.33,Up,1779194948,0xdc05e7cef6fb948abfee6d7ad363f47f0917638f0d67ac1f582dccf546f88523
Bitcoin Up or Down - May 19, 8:40AM-8:45AM ET,Redeem,2.75,2.75,,1779194738,0x764dc7dc62cc949dbe8f2fe138df966b63db68e5840a72b3020bb050e505a7fc
Bitcoin Up or Down - May 19, 8:40AM-8:45AM ET,Buy,2.17803,2.75,Up,1779194649,0xa125652e7cf9e676f886c24a92ebfbf9c52ee21dd8d0b0c7f5540088e005b484
Bitcoin Up or Down - May 19, 8:35AM-8:40AM ET,Redeem,2.35,2.35,,1779194430,0xf7f784d705c61a7636bb78e1675747b3fb13a7806d4be2632998555f726d9780
Bitcoin Up or Down - May 19, 8:35AM-8:40AM ET,Buy,2.08537,2.35,Up,1779194348,0xfb6cbba83b4aab934d836e7c6d8a3b991424de66348d8d747aa26e429dcd8473
Bitcoin Up or Down - May 19, 4:25AM-4:30AM ET,Redeem,2,2,,1779179466,0x0a0541a69e71f13f7d598c615d3444194f56b641a3a31f18c51ffb3eb3fb53b2
Bitcoin Up or Down - May 19, 4:25AM-4:30AM ET,Buy,1.4294,2,Up,1779179351,0x0883ea415b7783993f92a89b1eeb5c306be6db7e0f7ac84ca1d9f79b1def9064
Bitcoin Up or Down - May 19, 4:15AM-4:20AM ET,Redeem,2.11,2.11,,1779178836,0x8073e808c28feebb8f49a26841a06015a1a59d601c026c87173a8224f4ecd6d4
Bitcoin Up or Down - May 19, 4:15AM-4:20AM ET,Buy,2.07069,2.11,Up,1779178750,0xd056a76ccb82dafbc953adc5f33b08cd296ad5cd86a997c7acd2405ea7796046
Bitcoin Up or Down - May 19, 3:10AM-3:15AM ET,Redeem,2.1,2.1,,1779174932,0x6739a671d6e8ddef1ff71c485b27824ad146db5bb33ce876c31fcac21f27a2c7
Bitcoin Up or Down - May 19, 3:10AM-3:15AM ET,Buy,2.06088,2.1,Up,1779174851,0x32cb34b46cf7e16ea195c230477b5adeb438e4165ca7b0adf98a29bcabe660d1
Bitcoin Up or Down - May 19, 2:35AM-2:40AM ET,Redeem,2.5,2.5,,1779172835,0x7a33ba2af0078180bc57c9c09fb3341a294facb1f847b8391f3c0d9df62629b5
Bitcoin Up or Down - May 19, 2:35AM-2:40AM ET,Buy,1.5912300000000001,2.5,Up,1779172751,0xf6f22e17b078d503286a7affccb603901c26e9d41a1059e26abf70bf20af9875
Bitcoin Up or Down - May 19, 2:30AM-2:35AM ET,Redeem,1.97,1.97,,1779172529,0x4f6ae37630b42438fdcd747bb60180394b03fa9065467422d5ef88a679897ff9
Bitcoin Up or Down - May 19, 2:30AM-2:35AM ET,Buy,1.9333,1.97,Up,1779172452,0xb27d6f35288e75bf88669572836be632b1b8121584c2b228c4ffcdb97111f6d6
Bitcoin Up or Down - May 19, 1:40AM-1:45AM ET,Buy,2.16219,2.73,Up,1779169451,0xc9e79702d110897002c21174f38f991920e8c796acb8c33d0554cbb59769a266
Bitcoin Up or Down - May 19, 1:35AM-1:40AM ET,Redeem,2.23,2.23,,1779169265,0xffe1949ab600b6da05d371b9c7855628ba8f0a814f3c42fc9146c0bc46b49128
Bitcoin Up or Down - May 19, 1:35AM-1:40AM ET,Buy,2.18845,2.23,Up,1779169157,0x6875c6939140798d5da6c7928b147cfbf72aac8441a637a436ab8325e276c90d
Bitcoin Up or Down - May 19, 12:45AM-12:50AM ET,Redeem,2.52,2.52,,1779166227,0x3477edf2c0a69d13740c4d5988468654d3dd628b063f6fed60a027a11bede26a
Bitcoin Up or Down - May 19, 12:45AM-12:50AM ET,Buy,2.04422,2.52,Up,1779166150,0xd68592bcf9f24fb7f979062c7949c939f9d3cc42b6bdef51604afd64d0c318cc
Bitcoin Up or Down - May 19, 12:40AM-12:45AM ET,Redeem,2.25,2.25,,1779165977,0x8491b59d71a9e206c9133e0cd79031973461666063b309e2c9a45157f93f9039
Bitcoin Up or Down - May 19, 12:40AM-12:45AM ET,Buy,2.1449800000000003,2.25,Up,1779165851,0xefeb691f6f23ac83acd2757c257ccddd132b7e5590b66b9d8a6a2ad6830c369e
Bitcoin Up or Down - May 19, 12:10AM-12:15AM ET,Redeem,2.19,2.19,,1779164131,0x14a69161dbe4f1ac5ffa1984a9586a0d3828613bd5d1ad721ecec53596b8a8dc
Bitcoin Up or Down - May 19, 12:10AM-12:15AM ET,Buy,2.1287599999999998,2.19,Up,1779164052,0xed5759e9d30689252398b8b6ee33fba1112d4f31a5abc7603f849ee355ee1732
Bitcoin Up or Down - May 19, 12:05AM-12:10AM ET,Redeem,2.17,2.17,,1779163832,0x5c443e79ce4bca1b4ebaa88464bc707e2b8cdcee7674b4d456d0a5aed3031d6b
Bitcoin Up or Down - May 19, 12:05AM-12:10AM ET,Buy,2.00757,2.17,Up,1779163751,0x038867c1b13664aa5333030a3ac5cad86f9c4413974fd01c799729b509786ef4
"""

    # Load data
    df = load_data_from_csv(csv_data)
    
    # Calculate trades with proper loss handling
    trades_df = calculate_trades_corrected(df)
    
    # Calculate statistics
    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df['pnl'] > 0])
    losing_trades = len(trades_df[trades_df['pnl'] < 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_pnl = trades_df['pnl'].sum()
    avg_pnl = trades_df['pnl'].mean()
    avg_roi = trades_df[trades_df['pnl_pct'] > -100]['pnl_pct'].mean()  # Exclude -100% losses
    
    # Print summary
    print("=" * 90)
    print("CORRECTED TRADING PERFORMANCE ANALYSIS - May 19, 2026")
    print("=" * 90)
    print(f"\nTotal Trades:          {total_trades}")
    print(f"Winning Trades:        {winning_trades}")
    print(f"Losing Trades:         {losing_trades}")
    print(f"Win Rate:              {win_rate:.1f}%")
    print(f"\nTotal PnL:             ${total_pnl:.4f}")
    print(f"Average PnL/Trade:     ${avg_pnl:.4f}")
    print(f"Average ROI:           {avg_roi:.2f}%")
    print(f"Best Trade:            ${trades_df['pnl'].max():.4f} ({trades_df.loc[trades_df['pnl'].idxmax(), 'pnl_pct']:.2f}%)")
    print(f"Worst Trade:           ${trades_df['pnl'].min():.4f} ({trades_df.loc[trades_df['pnl'].idxmin(), 'pnl_pct']:.2f}%)")
    
    print(f"\nCompleted Trades:      {len(trades_df[trades_df['status'] == 'COMPLETED'])}")
    print(f"Unmatched Buys:        {len(trades_df[trades_df['status'] == 'UNMATCHED_BUY'])}")
    
    print("\n" + "=" * 90)
    print("DETAILED TRADE LIST")
    print("=" * 90)
    print(trades_df[['entry_time', 'status', 'entry_price', 'exit_usdc', 'pnl', 'pnl_pct']].to_string(index=False))
    
    # Create output directory
    output_dir = Path("charts-may19-2026")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create visualizations
    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(3, 2, hspace=0.35, wspace=0.3)
    
    # 1. PnL per Trade (with color coding)
    ax1 = fig.add_subplot(gs[0, 0])
    colors = ['green' if x > 0 else 'red' for x in trades_df['pnl']]
    bars = ax1.bar(range(len(trades_df)), trades_df['pnl'], color=colors, alpha=0.7, edgecolor='black', linewidth=0.5)
    ax1.axhline(y=0, color='black', linestyle='-', linewidth=1)
    ax1.set_xlabel('Trade #', fontweight='bold')
    ax1.set_ylabel('PnL ($)', fontweight='bold')
    ax1.set_title('PnL per Trade (Green=Win, Red=Loss)', fontweight='bold', fontsize=11)
    ax1.grid(axis='y', alpha=0.3)
    
    # 2. Entry Price vs PnL
    ax2 = fig.add_subplot(gs[0, 1])
    scatter = ax2.scatter(trades_df['entry_price'], trades_df['pnl'], 
                          c=trades_df['pnl'], cmap='RdYlGn', s=120, alpha=0.7, edgecolors='black', linewidth=0.5)
    ax2.axhline(y=0, color='black', linestyle='--', linewidth=1)
    ax2.set_xlabel('Entry Price ($)', fontweight='bold')
    ax2.set_ylabel('PnL ($)', fontweight='bold')
    ax2.set_title('Entry Price vs PnL', fontweight='bold', fontsize=11)
    plt.colorbar(scatter, ax=ax2, label='PnL ($)')
    ax2.grid(alpha=0.3)
    
    # 3. Cumulative PnL
    ax3 = fig.add_subplot(gs[1, 0])
    cumulative_pnl = trades_df['pnl'].cumsum()
    ax3.plot(cumulative_pnl, marker='o', linewidth=2.5, markersize=7, color='navy', label='Cumulative PnL')
    ax3.fill_between(range(len(cumulative_pnl)), cumulative_pnl, alpha=0.3, color='navy')
    ax3.axhline(y=0, color='red', linestyle='--', linewidth=1.5, label='Break-even')
    ax3.set_xlabel('Trade #', fontweight='bold')
    ax3.set_ylabel('Cumulative PnL ($)', fontweight='bold')
    ax3.set_title(f'Cumulative PnL Progression (Total: ${total_pnl:.4f})', fontweight='bold', fontsize=11)
    ax3.legend(loc='best')
    ax3.grid(alpha=0.3)
    
    # 4. Win/Loss Distribution
    ax4 = fig.add_subplot(gs[1, 1])
    sizes = [winning_trades, losing_trades]
    colors_pie = ['#2ecc71', '#e74c3c']
    explode = (0.05, 0.05)
    wedges, texts, autotexts = ax4.pie(sizes, labels=['Wins', 'Losses'], autopct='%1.1f%%',
                                         colors=colors_pie, explode=explode, startangle=90,
                                         textprops={'fontsize': 11, 'fontweight': 'bold'})
    ax4.set_title(f'Win Rate: {win_rate:.1f}% ({winning_trades}/{total_trades})', fontweight='bold', fontsize=11)
    
    # 5. ROI Distribution (histogram)
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.hist(trades_df['pnl_pct'], bins=15, color='steelblue', alpha=0.7, edgecolor='black', linewidth=0.5)
    ax5.axvline(x=avg_roi, color='red', linestyle='--', linewidth=2, label=f'Mean: {avg_roi:.2f}%')
    ax5.set_xlabel('ROI (%)', fontweight='bold')
    ax5.set_ylabel('Frequency', fontweight='bold')
    ax5.set_title('ROI Distribution', fontweight='bold', fontsize=11)
    ax5.legend()
    ax5.grid(alpha=0.3, axis='y')
    
    # 6. Account Balance Over Time (cumulative)
    ax6 = fig.add_subplot(gs[2, 1])
    starting_balance = 20.0
    account_balance = starting_balance + cumulative_pnl
    ax6.plot(account_balance, marker='s', linewidth=2.5, markersize=7, color='darkgreen', label='Account Balance')
    ax6.axhline(y=starting_balance, color='gray', linestyle=':', linewidth=1.5, label='Starting Balance')
    ax6.fill_between(range(len(account_balance)), starting_balance, account_balance, 
                     where=(account_balance >= starting_balance), alpha=0.3, color='green', interpolate=True)
    ax6.fill_between(range(len(account_balance)), starting_balance, account_balance, 
                     where=(account_balance < starting_balance), alpha=0.3, color='red', interpolate=True)
    ax6.set_xlabel('Trade #', fontweight='bold')
    ax6.set_ylabel('Account Balance ($)', fontweight='bold')
    ax6.set_title(f'Account Balance Progression (Start: ${starting_balance:.2f} → End: ${account_balance.iloc[-1]:.2f})', 
                  fontweight='bold', fontsize=11)
    ax6.legend(loc='best')
    ax6.grid(alpha=0.3)
    
    # Overall title
    fig.suptitle(f'Trading Performance Analysis - May 19, 2026 | Total PnL: ${total_pnl:.4f} | Win Rate: {win_rate:.1f}%', 
                 fontsize=14, fontweight='bold', y=0.995)
    
    # Save figure
    output_file = output_dir / 'trading_performance_analysis.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\n✓ Chart saved to: {output_file}")
    
    # Save detailed trades to CSV
    trades_csv = output_dir / 'trades_detailed.csv'
    trades_df.to_csv(trades_csv, index=False)
    print(f"✓ Detailed trades saved to: {trades_csv}")
    
    # Save summary stats
    summary_file = output_dir / 'summary_stats.txt'
    with open(summary_file, 'w') as f:
        f.write("=" * 90 + "\n")
        f.write("TRADING PERFORMANCE SUMMARY - May 19, 2026\n")
        f.write("=" * 90 + "\n\n")
        f.write(f"Total Trades:           {total_trades}\n")
        f.write(f"Winning Trades:         {winning_trades}\n")
        f.write(f"Losing Trades:          {losing_trades}\n")
        f.write(f"Win Rate:               {win_rate:.1f}%\n\n")
        f.write(f"Total PnL:              ${total_pnl:.4f}\n")
        f.write(f"Average PnL/Trade:      ${avg_pnl:.4f}\n")
        f.write(f"Average ROI:            {avg_roi:.2f}%\n")
        f.write(f"Best Trade:             ${trades_df['pnl'].max():.4f} ({trades_df.loc[trades_df['pnl'].idxmax(), 'pnl_pct']:.2f}%)\n")
        f.write(f"Worst Trade:            ${trades_df['pnl'].min():.4f} ({trades_df.loc[trades_df['pnl'].idxmin(), 'pnl_pct']:.2f}%)\n\n")
        f.write(f"Completed Trades:       {len(trades_df[trades_df['status'] == 'COMPLETED'])}\n")
        f.write(f"Unmatched Buys:         {len(trades_df[trades_df['status'] == 'UNMATCHED_BUY'])}\n")
    print(f"✓ Summary stats saved to: {summary_file}")
    
    print("\n" + "=" * 90)
    plt.show()

if __name__ == '__main__':
    main()
