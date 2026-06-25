import duckdb
import pandas as pd
import time
import os

def run_fast_orb():
    print("Running blazing fast DuckDB ORB...")
    start = time.time()
    
    start_ts = int(pd.Timestamp('2025-06-01', tz='UTC').timestamp())
    end_ts = int(pd.Timestamp('2026-06-01', tz='UTC').timestamp())
    
    sql = f"""
    WITH base AS (
        SELECT 
            symbol,
            timestamp,
            timezone('Asia/Kolkata', to_timestamp(timestamp)) as dt_ist,
            open, high, low, close, volume,
            CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) as date_ist,
            strftime(timezone('Asia/Kolkata', to_timestamp(timestamp)), '%H:%M') as time_ist
        FROM market_data
        WHERE timestamp >= {start_ts} AND timestamp <= {end_ts} AND interval = '1m'
    ),
    orb AS (
        SELECT 
            symbol, 
            date_ist,
            MAX(high) as orb_high,
            MIN(low) as orb_low
        FROM base
        WHERE time_ist >= '09:15' AND time_ist < '09:30'
        GROUP BY symbol, date_ist
    ),
    joined AS (
        SELECT 
            b.*, 
            o.orb_high, 
            o.orb_low,
            AVG(b.volume) OVER (PARTITION BY b.symbol ORDER BY b.timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) as sma_vol_20
        FROM base b
        JOIN orb o ON b.symbol = o.symbol AND b.date_ist = o.date_ist
    ),
    signals AS (
        SELECT 
            *,
            (volume / NULLIF(sma_vol_20, 0)) as rvol,
            CASE WHEN close > orb_high AND (volume / NULLIF(sma_vol_20, 0)) > 4.0 AND time_ist >= '09:30' AND time_ist <= '11:00' THEN 1 ELSE 0 END as signal_long,
            CASE WHEN close < orb_low AND (volume / NULLIF(sma_vol_20, 0)) > 4.0 AND time_ist >= '09:30' AND time_ist <= '11:00' THEN 1 ELSE 0 END as signal_short
        FROM joined
    )
    SELECT * FROM signals WHERE signal_long=1 OR signal_short=1 ORDER BY symbol, timestamp;
    """
    
    con = duckdb.connect('db/historify.duckdb', read_only=True)
    df = con.execute(sql).df()
    print(f"Query took {time.time()-start:.2f}s, found {len(df)} raw signal bars")
    
    print("Now evaluating forward paths...")
    sim_start = time.time()
    
    trades = []
    
    for i, row in df.iterrows():
        sym = row['symbol']
        ts = row['timestamp']
        date_ist = row['date_ist']
        
        if i > 0 and df.loc[i-1, 'symbol'] == sym and df.loc[i-1, 'date_ist'] == date_ist:
            continue
            
        side = 'LONG' if row['signal_long'] == 1 else 'SHORT'
        
        fwd = con.execute(f"""
            SELECT open, high, low, close, 
            CAST(strftime(timezone('Asia/Kolkata', to_timestamp(timestamp)), '%H:%M') AS VARCHAR) as time_ist
            FROM market_data
            WHERE symbol='{sym}' AND timestamp > {ts} AND timestamp <= {ts + 6*3600}
            AND interval='1m'
            ORDER BY timestamp
        """).fetchall()
        
        entry_price = float(row['close']) 
        qty = max(int((50000 * 5) / entry_price), 1)
        
        target = entry_price * 1.0025 if side == 'LONG' else entry_price * 0.9975
        stop = entry_price * 0.9925 if side == 'LONG' else entry_price * 1.0075
        
        trade_closed = False
        
        for bar in fwd:
            b_open, b_high, b_low, b_close, b_time = bar
            
            if b_time >= '15:15':
                pnl = (b_open - entry_price) * qty * (1 if side=='LONG' else -1)
                trades.append({'symbol': sym, 'pnl': pnl, 'reason': 'EOD'})
                trade_closed = True
                break
                
            if side == 'LONG':
                if b_high >= target:
                    pnl = (target - entry_price) * qty
                    trades.append({'symbol': sym, 'pnl': pnl, 'reason': 'TARGET'})
                    trade_closed = True
                    break
                elif b_low <= stop:
                    pnl = (stop - entry_price) * qty
                    trades.append({'symbol': sym, 'pnl': pnl, 'reason': 'STOP'})
                    trade_closed = True
                    break
            else:
                if b_low <= target:
                    pnl = (entry_price - target) * qty
                    trades.append({'symbol': sym, 'pnl': pnl, 'reason': 'TARGET'})
                    trade_closed = True
                    break
                elif b_high >= stop:
                    pnl = (entry_price - stop) * qty
                    trades.append({'symbol': sym, 'pnl': pnl, 'reason': 'STOP'})
                    trade_closed = True
                    break
                    
        if not trade_closed:
            if fwd:
                b_close = fwd[-1][3]
                pnl = (b_close - entry_price) * qty * (1 if side=='LONG' else -1)
                trades.append({'symbol': sym, 'pnl': pnl, 'reason': 'EOD'})
                
    print(f"Simulation took {time.time()-sim_start:.2f}s")
    
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
    run_fast_orb()
