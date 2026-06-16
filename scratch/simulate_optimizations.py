import json
import pandas as pd
import duckdb

print("Loading 10-year trade data...")
with open('bot4_10yr_verified.json') as f:
    data = json.load(f)

trades = data['trades']
df = pd.DataFrame(trades)
df['entry_time'] = pd.to_datetime(df['entry_time'])
df['date'] = df['entry_time'].dt.date.astype(str)
df['day_name'] = df['entry_time'].dt.day_name()
df['month'] = df['entry_time'].dt.month

print("Loading 30-day Moving Average Premiums from DuckDB...")
con = duckdb.connect('db/historify.duckdb', read_only=True)
bhav_rows = con.execute("SELECT date, straddle_open FROM options_daily_premiums WHERE symbol='NIFTY' ORDER BY date").fetchall()
con.close()

real_premiums = {}
ma30_premiums = {}
history = []
for row in bhav_rows:
    d = str(row[0])
    s = float(row[1])
    real_premiums[d] = s
    history.append(s)
    if len(history) > 30:
        history.pop(0)
    ma30_premiums[d] = sum(history) / len(history)

print("Simulating Optimizations...")
optimized_trades = []
for idx, row in df.iterrows():
    d = row['date']
    day_name = row['day_name']
    month = row['month']
    pnl = row['net_pnl']
    
    # UPGRADE 1: Low IV Filter
    if d in real_premiums and d in ma30_premiums:
        if real_premiums[d] < ma30_premiums[d] * 0.85:
            # Skip this day entirely
            continue
            
    # UPGRADE 2: Friday Risk Reduction
    # We simulate the tighter SL by reducing the loss size on Fridays where PNL < -1000
    if day_name == 'Friday' and pnl < -1000:
        pnl = pnl * 0.7  # 30% tighter SL
        
    # UPGRADE 3: Earnings Season Capital Reduction
    if month in [4, 5]:
        pnl = pnl * 0.5  # Halved lot size
        
    optimized_trades.append(pnl)

# Recalculate Metrics
opt_pnl = sum(optimized_trades)
opt_win_rate = len([x for x in optimized_trades if x > 0]) / len(optimized_trades)
opt_total_trades = len(optimized_trades)

old_pnl = data['metrics']['net_pnl']
old_win_rate = data['metrics']['win_rate_pct'] / 100
old_trades = data['metrics']['total_trades']

print("\n" + "="*50)
print("HYPOTHETICAL OPTIMIZED 10-YEAR METRICS")
print("="*50)
print(f"Total Net PnL:")
print(f"  Old: Rs. {old_pnl:.2f}")
print(f"  New: Rs. {opt_pnl:.2f} (Difference: +{opt_pnl - old_pnl:.2f})")
print(f"\nWin Rate:")
print(f"  Old: {old_win_rate*100:.2f}%")
print(f"  New: {opt_win_rate*100:.2f}%")
print(f"\nTotal Trades Taken:")
print(f"  Old: {old_trades}")
print(f"  New: {opt_total_trades}")
print("="*50)
