import duckdb
import pandas as pd
import numpy as np
import time
import os

def compute_vwap_stats(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    daily_groups = df.index.floor('D')
    cum_vol = df["volume"].groupby(daily_groups).cumsum()
    cum_tp_vol = (tp * df["volume"]).groupby(daily_groups).cumsum()
    vwap = cum_tp_vol / cum_vol
    
    # Calculate daily rolling variance for Z-Score
    diff_sq = (tp - vwap) ** 2
    cum_diff_sq = diff_sq.groupby(daily_groups).cumsum()
    counts = df.groupby(daily_groups).cumcount() + 1
    variance = cum_diff_sq / counts
    vwap_std = np.sqrt(variance)
    vwap_std = vwap_std.replace(0, 1e-6) # avoid div0
    
    z_score = (tp - vwap) / vwap_std
    return z_score

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def run_experiment():
    print("Loading data...")
    start = time.time()
    con = duckdb.connect('db/historify.duckdb', read_only=True)
    # 1 Year data: June 1, 2025 to June 1, 2026
    start_ts = int(pd.Timestamp('2025-06-01', tz='UTC').timestamp())
    end_ts = int(pd.Timestamp('2026-06-01', tz='UTC').timestamp())
    
    df = con.execute(f"""
        SELECT symbol, timestamp, open, high, low, close, volume 
        FROM market_data 
        WHERE timestamp >= {start_ts} AND timestamp <= {end_ts}
        AND interval = '1m'
        ORDER BY symbol, timestamp
    """).df()
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    print(f"Loaded {len(df)} rows in {time.time()-start:.2f}s")

    print("Calculating indicators...")
    start = time.time()
    
    grouped = df.groupby('symbol')
    trades = []
    
    for symbol, group in grouped:
        group = group.set_index('datetime').sort_index()
        z_score = compute_vwap_stats(group)
        rsi = compute_rsi(group['close'], 14)
        
        sma_vol = group['volume'].rolling(20, min_periods=1).mean()
        rvol = group['volume'] / sma_vol.replace(0, np.nan)
        rvol = rvol.fillna(0)
        
        times = group.index.time
        # Time mask matching the implementation plan
        time_mask = (times >= pd.to_datetime('09:30').time()) & (times <= pd.to_datetime('14:45').time())
        
        # ENTRY RULES (Much stricter for 90%+ win rate)
        # Z-Score > 3.5 means price is far above VWAP
        # Z-Score < -3.5 means price is far below VWAP
        long_cond = (z_score < -3.5) & (rsi < 15) & (rvol > 4.0) & time_mask
        short_cond = (z_score > 3.5) & (rsi > 85) & (rvol > 4.0) & time_mask
        
        in_trade = False
        side = None
        entry_price = 0
        qty = 0
        target = 0
        stop = 0
        
        closes = group['close'].to_numpy()
        highs = group['high'].to_numpy()
        lows = group['low'].to_numpy()
        opens = group['open'].to_numpy()
        timestamps = group.index
        
        l_cond_arr = long_cond.to_numpy()
        s_cond_arr = short_cond.to_numpy()
        
        for i in range(1, len(group)):
            # Evaluate on bar i-1 (closed bar), enter on bar i (open)
            c_long = l_cond_arr[i-1]
            c_short = s_cond_arr[i-1]
            
            cur_time = timestamps[i].time()
            
            if in_trade:
                # EOD Square off
                if cur_time >= pd.to_datetime('15:15').time():
                    exit_px = opens[i]
                    pnl = (exit_px - entry_price) * qty * (1 if side=='LONG' else -1)
                    trades.append({'symbol': symbol, 'pnl': pnl, 'side': side, 'reason': 'EOD'})
                    in_trade = False
                    continue
                
                if side == 'LONG':
                    if highs[i] >= target:
                        pnl = (target - entry_price) * qty
                        trades.append({'symbol': symbol, 'pnl': pnl, 'side': side, 'reason': 'TARGET'})
                        in_trade = False
                    elif lows[i] <= stop:
                        pnl = (stop - entry_price) * qty
                        trades.append({'symbol': symbol, 'pnl': pnl, 'side': side, 'reason': 'STOP'})
                        in_trade = False
                else: # SHORT
                    if lows[i] <= target:
                        pnl = (entry_price - target) * qty
                        trades.append({'symbol': symbol, 'pnl': pnl, 'side': side, 'reason': 'TARGET'})
                        in_trade = False
                    elif highs[i] >= stop:
                        pnl = (entry_price - stop) * qty
                        trades.append({'symbol': symbol, 'pnl': pnl, 'side': side, 'reason': 'STOP'})
                        in_trade = False
            else:
                if c_long:
                    in_trade = True
                    side = 'LONG'
                    entry_price = opens[i]
                    qty = max(int((50000 * 5) / entry_price), 1)
                    target = entry_price * (1 + 0.003) # 0.3% target
                    stop = entry_price * (1 - 0.010)   # 1.0% structural stop
                elif c_short:
                    in_trade = True
                    side = 'SHORT'
                    entry_price = opens[i]
                    qty = max(int((50000 * 5) / entry_price), 1)
                    target = entry_price * (1 - 0.003)
                    stop = entry_price * (1 + 0.010)
                    
    print(f"Simulation finished in {time.time()-start:.2f}s")
    
    if len(trades) == 0:
        print("No trades found.")
        return
        
    wins = sum(1 for t in trades if t['pnl'] > 0)
    gross_pnl = sum(t['pnl'] for t in trades)
    net_pnl = sum(t['pnl'] - 18.0 for t in trades)
    
    print(f"\n--- RESULTS A: VWAP Mean Reversion ---")
    print(f"Total Trades: {len(trades)}")
    print(f"Win Rate: {wins/len(trades)*100:.2f}%")
    print(f"Gross PnL: Rs {gross_pnl:.2f}")
    print(f"Net PnL (after Rs 18 fee): Rs {net_pnl:.2f}")
    
    reasons = {}
    for t in trades:
        reasons[t['reason']] = reasons.get(t['reason'], 0) + 1
    print(f"Exit Reasons: {reasons}")

if __name__ == '__main__':
    run_experiment()
