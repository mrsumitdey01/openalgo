import json
import pandas as pd
import numpy as np
from datetime import datetime

with open('bot4_10yr_verified.json') as f:
    data = json.load(f)

trades = data['trades']
df = pd.DataFrame(trades)

# Convert entry_time to datetime
df['entry_time'] = pd.to_datetime(df['entry_time'])
df['date'] = df['entry_time'].dt.date
df['day_of_week'] = df['entry_time'].dt.day_name()
df['month'] = df['entry_time'].dt.month
df['year'] = df['entry_time'].dt.year

# Calculate outcome
df['is_win'] = df['net_pnl'] > 0

# --- 1. Day of Week Analysis ---
print("--- Day of the Week Performance ---")
dow_stats = df.groupby('day_of_week').agg(
    total_trades=('id', 'count'),
    win_rate=('is_win', 'mean'),
    avg_pnl=('net_pnl', 'mean'),
    total_pnl=('net_pnl', 'sum')
).sort_values('total_pnl', ascending=False)
print(dow_stats)
print("\n")

# --- 2. Month Analysis ---
print("--- Month Performance ---")
month_stats = df.groupby('month').agg(
    total_trades=('id', 'count'),
    win_rate=('is_win', 'mean'),
    avg_pnl=('net_pnl', 'mean')
).sort_values('avg_pnl', ascending=False)
print(month_stats)
print("\n")

# --- 3. Year Analysis ---
print("--- Year Performance ---")
year_stats = df.groupby('year').agg(
    total_trades=('id', 'count'),
    win_rate=('is_win', 'mean'),
    avg_pnl=('net_pnl', 'mean'),
    total_pnl=('net_pnl', 'sum')
)
print(year_stats)
print("\n")

# --- 4. Premium Size (Volatility Proxy) Analysis ---
# High premium means high VIX
df['premium_bin'] = pd.qcut(df['entry_price'], q=4, labels=['Low VIX', 'Med-Low VIX', 'Med-High VIX', 'High VIX'])
print("--- Entry Premium (VIX) Performance ---")
vix_stats = df.groupby('premium_bin').agg(
    total_trades=('id', 'count'),
    win_rate=('is_win', 'mean'),
    avg_pnl=('net_pnl', 'mean'),
    avg_loss=('net_pnl', lambda x: x[x <= 0].mean() if len(x[x <= 0]) > 0 else 0)
)
print(vix_stats)
print("\n")

# --- 5. Worst 20 Losses Analysis ---
print("--- Top 20 Worst Losses ---")
worst = df.sort_values('net_pnl').head(20)
print(worst[['date', 'day_of_week', 'entry_price', 'net_pnl']])
