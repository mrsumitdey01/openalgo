import pandas as pd
import duckdb
from datetime import datetime
import itertools

DB_PATH = 'db/historify.duckdb'

def optimize_bot4(symbol):
    con = duckdb.connect(DB_PATH)
    query = f"""
    SELECT timestamp, open, high, low, close 
    FROM market_data 
    WHERE symbol='{symbol}'
    ORDER BY timestamp ASC
    """
    df = con.execute(query).df()
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df.set_index('datetime', inplace=True)
    
    # Filter for 2025 and 2026
    df = df[df.index.year >= 2025]
    
    grouped = df.groupby(df.index.date)
    
    # Optimization space
    sl_pcts = [0.003, 0.004, 0.005, 0.006, 0.007] # Spot proxy for 15% to 35% option premium
    trail_drawdown_pcts = [0.3, 0.5, 0.7] # 30%, 50%, 70% of peak profit allowed to be given back
    mtm_start_pcts = [0.004, 0.005, 0.006] # When to start trailing
    
    capital = 800000.0
    GAP_ABORT_PCT = 0.005
    
    results = []
    
    # Pre-process valid days
    valid_days = []
    prev_close = None
    for date, day_df in grouped:
        if len(day_df) < 300: 
            if len(day_df) > 0: prev_close = day_df.iloc[-1]['close']
            continue
            
        day_open = day_df.iloc[0]['open']
        day_close = day_df.iloc[-1]['close']
        
        if prev_close is None:
            prev_close = day_close
            continue
            
        gap_pct = abs(day_open - prev_close) / prev_close
        if gap_pct > GAP_ABORT_PCT:
            prev_close = day_close
            continue
            
        valid_days.append(day_df)
        prev_close = day_close

    print(f"Valid Days to test: {len(valid_days)}")
    
    combinations = list(itertools.product(sl_pcts, trail_drawdown_pcts, mtm_start_pcts))
    total_combs = len(combinations)
    
    for i, (sl, trail_dd, mtm_start) in enumerate(combinations):
        total_pnl = 0
        wins = 0
        losses = 0
        max_drawdown = 0
        peak_equity = 0
        
        for day_df in valid_days:
            date = day_df.index[0].date()
            current_qty = 65
            if date.weekday() == 2: # Wednesday risk reduction
                current_qty = 32
                
            ce_entry = pe_entry = None
            ce_sl = pe_sl = None
            ce_open = pe_open = False
            entered = False
            
            peak_mtm = 0
            day_pnl = 0
            aborted_for_day = False
            
            for idx, row in day_df.iterrows():
                current_time = idx.time()
                current_price = row['close']
                
                if current_time.hour == 9 and current_time.minute == 21 and not entered:
                    ce_entry = pe_entry = current_price
                    ce_sl = current_price + (current_price * sl)
                    pe_sl = current_price - (current_price * sl)
                    ce_open = pe_open = entered = True
                    continue
                    
                if entered and not aborted_for_day:
                    current_mtm = 0
                    if ce_open: current_mtm += (ce_entry - current_price) * 0.5 * current_qty
                    if pe_open: current_mtm += (current_price - pe_entry) * 0.5 * current_qty
                        
                    total_current_mtm = day_pnl + current_mtm
                    if total_current_mtm > peak_mtm: peak_mtm = total_current_mtm
                        
                    if ce_open and current_price >= ce_sl:
                        ce_open = False
                        day_pnl += (ce_entry - ce_sl) * 0.5 * current_qty
                    if pe_open and current_price <= pe_sl:
                        pe_open = False
                        day_pnl += (pe_entry - pe_sl) * 0.5 * current_qty
                        
                    if peak_mtm > (capital * mtm_start):
                        # The trailing stop locks in at (peak_mtm * (1 - trail_dd))
                        trail_target = peak_mtm * (1 - trail_dd)
                        if total_current_mtm < trail_target:
                            aborted_for_day = True
                            if ce_open: day_pnl += (ce_entry - current_price) * 0.5 * current_qty
                            if pe_open: day_pnl += (current_price - pe_entry) * 0.5 * current_qty
                            ce_open = pe_open = False
                            
                    if total_current_mtm < -(capital * 0.02):
                        aborted_for_day = True
                        day_pnl = -(capital * 0.02)
                        ce_open = pe_open = False
                    
                    if current_time.hour == 15 and current_time.minute == 15 and not aborted_for_day:
                        if ce_open: day_pnl += (ce_entry - current_price) * 0.5 * current_qty
                        if pe_open: day_pnl += (current_price - pe_entry) * 0.5 * current_qty
                        ce_open = pe_open = aborted_for_day = True
                        
            if entered:
                total_pnl += day_pnl
                if total_pnl > peak_equity: peak_equity = total_pnl
                dd = peak_equity - total_pnl
                if dd > max_drawdown: max_drawdown = dd
                    
                if day_pnl > 0: wins += 1
                elif day_pnl < 0: losses += 1
                
        results.append({
            'SL': sl,
            'Trail_DD': trail_dd,
            'MTM_Start': mtm_start,
            'PnL': total_pnl,
            'Wins': wins,
            'Losses': losses,
            'Max_DD': max_drawdown
        })
        print(f"Tested {i+1}/{total_combs}: SL={sl}, Trail={trail_dd}, Start={mtm_start} -> PnL: {total_pnl:.2f}")

    # Find the best
    df_res = pd.DataFrame(results)
    best_pnl = df_res.sort_values(by='PnL', ascending=False).head(3)
    best_dd = df_res.sort_values(by='Max_DD', ascending=True).head(3)
    
    print("\n--- TOP 3 MOST PROFITABLE ---")
    print(best_pnl)
    print("\n--- TOP 3 LOWEST DRAWDOWN ---")
    print(best_dd)

print("Starting deep parameter optimization for 2025-2026...")
optimize_bot4('NIFTY')
