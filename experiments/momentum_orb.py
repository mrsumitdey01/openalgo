import duckdb
import pandas as pd
import numpy as np
import time

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

    print("Calculating ORB...")
    start = time.time()
    
    grouped = df.groupby('symbol')
    trades = []
    
    for symbol, group in grouped:
        group = group.set_index('datetime').sort_index()
        
        # Calculate daily 15-min ORB high/low
        daily_groups = group.groupby(group.index.floor('D'))
        
        orb_highs = []
        orb_lows = []
        
        for name, d_group in daily_groups:
            mask_15m = (d_group.index.time >= pd.to_datetime('09:15').time()) & (d_group.index.time < pd.to_datetime('09:30').time())
            if not d_group[mask_15m].empty:
                orb_h = d_group[mask_15m]['high'].max()
                orb_l = d_group[mask_15m]['low'].min()
            else:
                orb_h = np.nan
                orb_l = np.nan
            
            d_group = d_group.copy()
            d_group['orb_high'] = orb_h
            d_group['orb_low'] = orb_l
            orb_highs.append(d_group['orb_high'])
            orb_lows.append(d_group['orb_low'])
            
        if not orb_highs:
            continue
            
        group['orb_high'] = pd.concat(orb_highs)
        group['orb_low'] = pd.concat(orb_lows)
        
        sma_vol = group['volume'].rolling(20, min_periods=1).mean()
        rvol = group['volume'] / sma_vol.replace(0, np.nan)
        rvol = rvol.fillna(0)
        
        times = group.index.time
        # Trade only during momentum hours
        time_mask = (times >= pd.to_datetime('09:30').time()) & (times <= pd.to_datetime('11:00').time())
        
        # ENTRY RULES
        long_cond = (group['close'] > group['orb_high']) & (rvol > 3.0) & time_mask
        short_cond = (group['close'] < group['orb_low']) & (rvol > 3.0) & time_mask
        
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
        
        # Only 1 trade per day per symbol to avoid overtrading chops
        last_trade_day = None
        
        for i in range(1, len(group)):
            c_long = l_cond_arr[i-1]
            c_short = s_cond_arr[i-1]
            
            cur_time = timestamps[i].time()
            cur_date = timestamps[i].date()
            
            if in_trade:
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
                else:
                    if lows[i] <= target:
                        pnl = (entry_price - target) * qty
                        trades.append({'symbol': symbol, 'pnl': pnl, 'side': side, 'reason': 'TARGET'})
                        in_trade = False
                    elif highs[i] >= stop:
                        pnl = (entry_price - stop) * qty
                        trades.append({'symbol': symbol, 'pnl': pnl, 'side': side, 'reason': 'STOP'})
                        in_trade = False
            else:
                if cur_date != last_trade_day: # 1 trade per day limit
                    if c_long:
                        in_trade = True
                        side = 'LONG'
                        entry_price = opens[i]
                        qty = max(int((50000 * 5) / entry_price), 1)
                        target = entry_price * (1 + 0.003) # 0.3% target
                        stop = entry_price * (1 - 0.005)   # 0.5% stop
                        last_trade_day = cur_date
                    elif c_short:
                        in_trade = True
                        side = 'SHORT'
                        entry_price = opens[i]
                        qty = max(int((50000 * 5) / entry_price), 1)
                        target = entry_price * (1 - 0.003)
                        stop = entry_price * (1 + 0.005)
                        last_trade_day = cur_date
                    
    print(f"Simulation finished in {time.time()-start:.2f}s")
    
    if len(trades) == 0:
        print("No trades found.")
        return
        
    wins = sum(1 for t in trades if t['pnl'] > 0)
    gross_pnl = sum(t['pnl'] for t in trades)
    net_pnl = sum(t['pnl'] - 18.0 for t in trades)
    
    print(f"\n--- RESULTS B: ORB Momentum ---")
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
