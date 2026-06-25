import duckdb
import pandas as pd
import numpy as np
import time

pd.options.mode.chained_assignment = None

# --- PARAMS ---
ADX_PERIOD = 14
CAPITAL = 500000
FEE = 18

def compute_adx_atr(df):
    print("Computing ADX and ATR...")
    
    # Needs to be grouped by symbol if multiple symbols exist,
    # but we will apply this per symbol for safety.
    
    df['prev_close'] = df.groupby('symbol')['close'].shift(1)
    df['prev_high'] = df.groupby('symbol')['high'].shift(1)
    df['prev_low'] = df.groupby('symbol')['low'].shift(1)
    
    # TR
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['prev_close']).abs()
    tr3 = (df['low'] - df['prev_close']).abs()
    df['TR'] = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
    
    # DM
    up_move = df['high'] - df['prev_high']
    down_move = df['prev_low'] - df['low']
    
    df['+DM'] = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    df['-DM'] = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    # Wilder's Smoothing via EWM (alpha = 1/N)
    alpha = 1 / ADX_PERIOD
    
    df['ATR'] = df.groupby('symbol')['TR'].transform(lambda x: x.ewm(alpha=alpha, adjust=False).mean())
    df['+DI14'] = df.groupby('symbol')['+DM'].transform(lambda x: x.ewm(alpha=alpha, adjust=False).mean())
    df['-DI14'] = df.groupby('symbol')['-DM'].transform(lambda x: x.ewm(alpha=alpha, adjust=False).mean())
    
    df['+DI'] = 100 * (df['+DI14'] / df['ATR'])
    df['-DI'] = 100 * (df['-DI14'] / df['ATR'])
    
    dx = 100 * (df['+DI'] - df['-DI']).abs() / (df['+DI'] + df['-DI'])
    df['ADX'] = df.groupby('symbol')[dx.name].transform(lambda x: x.ewm(alpha=alpha, adjust=False).mean()) if dx.name else dx.groupby(df['symbol']).transform(lambda x: x.ewm(alpha=alpha, adjust=False).mean())
    
    return df

def simulate_trades(df, strategy='momentum'):
    # Assumes df is sorted by timestamp and is ONE symbol
    trades = []
    in_pos = False
    
    entry_price = 0
    qty = 0
    target = 0
    stop = 0
    side = None
    
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        time_hm = row['time_hm']
        
        if in_pos:
            # Check exits
            if side == 'LONG':
                if row['high'] >= target:
                    trades.append({'entry': entry_price, 'exit': target, 'qty': qty, 'side': side, 'reason': 'TARGET'})
                    in_pos = False
                elif row['low'] <= stop:
                    trades.append({'entry': entry_price, 'exit': stop, 'qty': qty, 'side': side, 'reason': 'STOP'})
                    in_pos = False
            else:
                if row['low'] <= target:
                    trades.append({'entry': entry_price, 'exit': target, 'qty': qty, 'side': side, 'reason': 'TARGET'})
                    in_pos = False
                elif row['high'] >= stop:
                    trades.append({'entry': entry_price, 'exit': stop, 'qty': qty, 'side': side, 'reason': 'STOP'})
                    in_pos = False
                    
            if in_pos and time_hm >= '15:15':
                trades.append({'entry': entry_price, 'exit': row['open'], 'qty': qty, 'side': side, 'reason': 'EOD'})
                in_pos = False
                
        else:
            # Check Entries
            if time_hm >= '09:30' and time_hm <= '11:00':
                
                if strategy == 'momentum':
                    # Momentum Matrix: Gap > 0.5%, Breaks ORB High, ADX > 25
                    if prev['gap_pct'] > 0.005 and prev['close'] > prev['orb_high'] and prev['ADX'] > 25:
                        entry_price = row['open']
                        qty = int((CAPITAL * 5) / entry_price)
                        atr = prev['ATR']
                        target = entry_price + (2.0 * atr)
                        stop = entry_price - (1.0 * atr)
                        side = 'LONG'
                        in_pos = True
                
                elif strategy == 'mean_revert':
                    # Mean Revert: Price far from VWAP, ADX < 20
                    if prev['close'] < prev['vwap'] * 0.99 and prev['ADX'] < 20:
                        entry_price = row['open']
                        qty = int((CAPITAL * 5) / entry_price)
                        atr = prev['ATR']
                        target = prev['vwap']
                        stop = entry_price - (1.0 * atr)
                        side = 'LONG'
                        in_pos = True
                        
    return trades

def run_experiment():
    print("Connecting to DuckDB...")
    con = duckdb.connect('db/historify.duckdb', read_only=True)
    
    # We fetch basic 1m data + VWAP + ORB
    # Using SQL to compute RVOL, VWAP, ORB reduces python load
    sql = """
    WITH base AS (
        SELECT 
            symbol,
            timestamp,
            open, high, low, close, volume,
            CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) as date_ist,
            strftime(timezone('Asia/Kolkata', to_timestamp(timestamp)), '%H:%M') as time_hm,
            SUM(volume * (high+low+close)/3) OVER (PARTITION BY symbol, CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) ORDER BY timestamp) /
            NULLIF(SUM(volume) OVER (PARTITION BY symbol, CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) ORDER BY timestamp), 0) as vwap,
            FIRST_VALUE(close) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) as global_prev_close
        FROM market_data
        WHERE exchange='NSE' 
          AND CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) >= '2023-01-01'
    ),
    orb AS (
        SELECT 
            symbol, date_ist,
            MAX(high) as orb_high,
            MIN(low) as orb_low,
            FIRST_VALUE(open) OVER (PARTITION BY symbol, date_ist ORDER BY time_hm) as open_915,
            FIRST_VALUE(close) OVER (PARTITION BY symbol ORDER BY date_ist ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING) as prev_day_close
        FROM base
        WHERE time_hm BETWEEN '09:15' AND '09:29'
        GROUP BY symbol, date_ist, time_hm, open, close
    ),
    orb_grouped AS (
        SELECT symbol, date_ist, MAX(orb_high) as orb_high, MIN(orb_low) as orb_low, FIRST(open_915) as open_915, FIRST(prev_day_close) as prev_day_close
        FROM orb GROUP BY symbol, date_ist
    )
    SELECT 
        b.symbol, b.timestamp, b.open, b.high, b.low, b.close, b.volume, b.time_hm, b.vwap,
        o.orb_high, o.orb_low,
        (o.open_915 / o.prev_day_close) - 1.0 as gap_pct
    FROM base b
    JOIN orb_grouped o ON b.symbol = o.symbol AND b.date_ist = o.date_ist
    ORDER BY b.symbol, b.timestamp
    """
    
    print("Executing huge SQL query...")
    start_sql = time.time()
    df = con.execute(sql).df()
    print(f"SQL execution took {time.time() - start_sql:.2f} seconds. Rows: {len(df)}")
    
    # Compute ADX and ATR
    start_adx = time.time()
    df = compute_adx_atr(df)
    print(f"ADX/ATR execution took {time.time() - start_adx:.2f} seconds.")
    
    strategies = ['momentum', 'mean_revert']
    
    for strat in strategies:
        print(f"--- RUNNING STRATEGY: {strat} ---")
        start_sim = time.time()
        
        all_trades = []
        for symbol, group in df.groupby('symbol'):
            trades = simulate_trades(group, strategy=strat)
            all_trades.extend(trades)
            
        print(f"Simulation took {time.time() - start_sim:.2f} seconds.")
        
        wins = 0
        gross_pnl = 0
        net_pnl = 0
        
        for t in all_trades:
            pnl = (t['exit'] - t['entry']) * t['qty'] if t['side'] == 'LONG' else (t['entry'] - t['exit']) * t['qty']
            gross_pnl += pnl
            net_pnl += (pnl - FEE)
            if pnl > 0:
                wins += 1
                
        total_trades = len(all_trades)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        print(f"Total Trades: {total_trades}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Gross PnL: Rs {gross_pnl:.2f}")
        print(f"Net PnL (after Rs {FEE} fee): Rs {net_pnl:.2f}\n")

if __name__ == "__main__":
    run_experiment()
