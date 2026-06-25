import duckdb
import pandas as pd
import time
import numpy as np

pd.options.mode.chained_assignment = None

CAPITAL = 500000
FEE = 18

def run_experiment():
    print("Connecting to DuckDB...")
    con = duckdb.connect('db/historify.duckdb', read_only=True)

    sql = """
    WITH base AS (
        SELECT 
            symbol,
            timestamp,
            open, high, low, close, volume,
            CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) as date_ist,
            strftime(timezone('Asia/Kolkata', to_timestamp(timestamp)), '%H:%M') as time_ist,
            -- RVOL SMA
            AVG(volume) OVER (PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) as sma_vol_20,
            -- VWAP
            SUM(volume * (high+low+close)/3) OVER (PARTITION BY symbol, CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) ORDER BY timestamp) /
            NULLIF(SUM(volume) OVER (PARTITION BY symbol, CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) ORDER BY timestamp), 0) as vwap
        FROM market_data
        WHERE exchange='NSE'
          AND interval='1m'
          AND CAST(timezone('Asia/Kolkata', to_timestamp(timestamp)) AS DATE) >= '2023-01-01'
    ),
    orb AS (
        SELECT 
            symbol, date_ist,
            MAX(high) as orb_high,
            MIN(low) as orb_low,
            FIRST_VALUE(open) OVER (PARTITION BY symbol, date_ist ORDER BY time_ist) as open_915,
            FIRST_VALUE(close) OVER (PARTITION BY symbol ORDER BY date_ist ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING) as prev_day_close
        FROM base
        WHERE time_ist BETWEEN '09:15' AND '09:29'
        GROUP BY symbol, date_ist, time_ist, open, close
    ),
    orb_grouped AS (
        SELECT symbol, date_ist, MAX(orb_high) as orb_high, MIN(orb_low) as orb_low, FIRST(open_915) as open_915, FIRST(prev_day_close) as prev_day_close
        FROM orb GROUP BY symbol, date_ist
    ),
    signals AS (
        SELECT 
            b.*,
            o.orb_high, o.orb_low,
            (o.open_915 / o.prev_day_close) - 1.0 as gap_pct
        FROM base b
        JOIN orb_grouped o ON b.symbol = o.symbol AND b.date_ist = o.date_ist
        WHERE b.time_ist >= '09:30' AND b.time_ist <= '11:00'
    )
    SELECT * FROM signals
    """

    print("Running DuckDB query...")
    start_time = time.time()
    df = con.execute(sql).df()
    print(f"Query took {time.time() - start_time:.2f}s, found {len(df)} signal bars")
    
    print("Computing Indicators locally using Pandas...")
    
    # 1. Momentum Matrix
    df['signal_mom'] = np.where(
        (df['gap_pct'] > 0.005) & 
        (df['close'] > df['orb_high']) & 
        (df['volume'] > (df['sma_vol_20'] * 2.0)), 1, 0)
        
    # 2. Confluence Mean-Revert
    df['signal_mr'] = np.where(
        (df['close'] < (df['vwap'] * 0.985)) & 
        (df['volume'] > (df['sma_vol_20'] * 2.0)), 1, 0)
    
    # Keep only first signal per day per symbol
    mom_signals = df[df['signal_mom'] == 1].groupby(['symbol', 'date_ist']).first().reset_index()
    mr_signals = df[df['signal_mr'] == 1].groupby(['symbol', 'date_ist']).first().reset_index()
    
    print(f"Total Momentum Signals: {len(mom_signals)}")
    print(f"Total Mean Revert Signals: {len(mr_signals)}")

    strategies = [('Momentum Matrix', mom_signals), ('Confluence Mean-Revert', mr_signals)]

    for strat_name, strat_df in strategies:
        print(f"\\n--- Evaluating {strat_name} ---")
        
        trades = []
        sim_start = time.time()
        
        for _, row in strat_df.iterrows():
            sym = row['symbol']
            ts = row['timestamp']
            entry_px = row['close']
            
            qty = int((CAPITAL * 5) / entry_px)
            if qty < 1: qty = 1
            
            if strat_name == 'Momentum Matrix':
                # Institutional asymmetric reward: risk 0.5%, target 1.5%
                target = entry_px * 1.015
                stop = entry_px * 0.995
            else: # Mean Revert
                target = row['vwap']
                # Limit the stop to 0.75%
                stop = entry_px * 0.9925

            # Query future bars for this symbol on this day
            future_sql = f"""
            SELECT high, low, close, strftime(timezone('Asia/Kolkata', to_timestamp(timestamp)), '%H:%M') as time_ist, open
            FROM market_data
            WHERE symbol='{sym}' AND timestamp > {ts} AND timestamp <= {ts + 6*3600}
            ORDER BY timestamp
            """
            future_df = con.execute(future_sql).df()
            
            exit_px = 0
            reason = ""
            for _, f_row in future_df.iterrows():
                if f_row['high'] >= target:
                    exit_px = target
                    reason = "TARGET"
                    break
                elif f_row['low'] <= stop:
                    exit_px = stop
                    reason = "STOP"
                    break
                elif f_row['time_ist'] >= '15:15':
                    exit_px = f_row['open']
                    reason = "EOD"
                    break
            
            if exit_px > 0:
                trades.append({
                    'entry': entry_px,
                    'exit': exit_px,
                    'qty': qty,
                    'reason': reason
                })

        print(f"Simulation took {time.time() - sim_start:.2f}s")
        
        wins = 0
        gross_pnl = 0
        net_pnl = 0
        for t in trades:
            pnl = (t['exit'] - t['entry']) * t['qty']
            gross_pnl += pnl
            net_pnl += (pnl - FEE)
            if pnl > 0: wins += 1
            
        total = len(trades)
        win_rate = (wins / total * 100) if total > 0 else 0
        
        print(f"Total Trades: {total}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"Gross PnL: Rs {gross_pnl:.2f}")
        print(f"Net PnL (after Rs {FEE} fee): Rs {net_pnl:.2f}")
        
if __name__ == "__main__":
    run_experiment()
