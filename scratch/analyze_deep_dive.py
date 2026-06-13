import pandas as pd
import duckdb
from datetime import datetime

DB_PATH = 'db/historify.duckdb'

def deep_dive_2025_2026(symbol):
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
    
    df = df[df.index.year >= 2025]
    grouped = df.groupby(df.index.date)
    
    sl_pct = 0.005 
    trail_dd_pct = 0.5 
    mtm_start_pct = 0.005 
    
    capital = 800000.0
    GAP_ABORT_PCT = 0.005
    
    prev_close = None
    trades = []
    
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
            
        current_qty = 65
        if date.weekday() == 2:
            current_qty = 32
            
        ce_entry = pe_entry = None
        ce_sl = pe_sl = None
        ce_open = pe_open = False
        entered = False
        
        peak_mtm = 0
        peak_mtm_time = None
        day_pnl = 0
        aborted_for_day = False
        exit_reason = "EOD"
        sl_hit_count = 0
        
        for idx, row in day_df.iterrows():
            current_time = idx.time()
            current_price = row['close']
            
            if current_time.hour == 9 and current_time.minute == 21 and not entered:
                ce_entry = pe_entry = current_price
                ce_sl = current_price + (current_price * sl_pct)
                pe_sl = current_price - (current_price * sl_pct)
                ce_open = pe_open = entered = True
                continue
                
            if entered and not aborted_for_day:
                current_mtm = 0
                if ce_open: current_mtm += (ce_entry - current_price) * 0.5 * current_qty
                if pe_open: current_mtm += (current_price - pe_entry) * 0.5 * current_qty
                    
                total_current_mtm = day_pnl + current_mtm
                if total_current_mtm > peak_mtm: 
                    peak_mtm = total_current_mtm
                    peak_mtm_time = current_time
                    
                if ce_open and current_price >= ce_sl:
                    ce_open = False
                    day_pnl += (ce_entry - ce_sl) * 0.5 * current_qty
                    sl_hit_count += 1
                if pe_open and current_price <= pe_sl:
                    pe_open = False
                    day_pnl += (pe_entry - pe_sl) * 0.5 * current_qty
                    sl_hit_count += 1
                    
                if peak_mtm > (capital * mtm_start_pct):
                    trail_target = peak_mtm * (1 - trail_dd_pct)
                    if total_current_mtm < trail_target:
                        aborted_for_day = True
                        if ce_open: day_pnl += (ce_entry - current_price) * 0.5 * current_qty
                        if pe_open: day_pnl += (current_price - pe_entry) * 0.5 * current_qty
                        ce_open = pe_open = False
                        exit_reason = "MTM_Trail"
                        
                if total_current_mtm < -(capital * 0.02):
                    aborted_for_day = True
                    day_pnl = -(capital * 0.02)
                    ce_open = pe_open = False
                    exit_reason = "Max_Loss"
                
                if current_time.hour == 15 and current_time.minute == 15 and not aborted_for_day:
                    if ce_open: day_pnl += (ce_entry - current_price) * 0.5 * current_qty
                    if pe_open: day_pnl += (current_price - pe_entry) * 0.5 * current_qty
                    ce_open = pe_open = aborted_for_day = True
                    exit_reason = f"EOD (SL Hits: {sl_hit_count})"
                    
        prev_close = day_close
        
        if entered:
            trades.append({
                'Date': date,
                'Qty': current_qty,
                'Peak_MTM': peak_mtm,
                'Peak_Time': peak_mtm_time,
                'Final_PnL': day_pnl,
                'Exit_Reason': exit_reason,
                'SL_Hits': sl_hit_count,
                'Left_On_Table': peak_mtm - day_pnl
            })
            
    df_trades = pd.DataFrame(trades)
    
    # Let's analyze what we left on the table during losing days
    losing_days = df_trades[df_trades['Final_PnL'] < 0]
    winning_days = df_trades[df_trades['Final_PnL'] > 0]
    
    print("--- 2025-2026 DEEP DIVE ---")
    print(f"Total Traded Days: {len(df_trades)}")
    print(f"Losing Days: {len(losing_days)}")
    
    print("\n--- LOSING DAYS ANALYSIS ---")
    for _, row in losing_days.iterrows():
        print(f"Date: {row['Date']} | PnL: {row['Final_PnL']:.2f} | Peak: {row['Peak_MTM']:.2f} at {row['Peak_Time']} | Exit: {row['Exit_Reason']} | SL Hits: {row['SL_Hits']}")
        
    print("\n--- MACRO ANALYSIS ---")
    # Average MTM Trail left on table
    mtm_exits = df_trades[df_trades['Exit_Reason'] == 'MTM_Trail']
    print(f"Days hit MTM Trail: {len(mtm_exits)}")
    if len(mtm_exits) > 0:
        avg_left = mtm_exits['Left_On_Table'].mean()
        avg_peak = mtm_exits['Peak_MTM'].mean()
        print(f"Average Peak MTM before Trail Hit: {avg_peak:.2f}")
        print(f"Average Profit Left on Table on MTM Hit: {avg_left:.2f}")
        
    print("\n--- SL HIT ANALYSIS ---")
    sl_days = df_trades[df_trades['SL_Hits'] > 0]
    print(f"Days with at least 1 SL hit: {len(sl_days)}")
    if len(sl_days) > 0:
        avg_pnl_sl_hit = sl_days['Final_PnL'].mean()
        print(f"Average PnL when an SL hits: {avg_pnl_sl_hit:.2f}")
        
    print("\n--- EOD HOLD ANALYSIS ---")
    eod_days = df_trades[df_trades['Exit_Reason'].str.contains('EOD')]
    print(f"Days held to EOD: {len(eod_days)}")
    if len(eod_days) > 0:
        avg_pnl_eod = eod_days['Final_PnL'].mean()
        avg_left_eod = eod_days['Left_On_Table'].mean()
        print(f"Average PnL for EOD hold: {avg_pnl_eod:.2f}")
        print(f"Average Profit Left on Table at EOD (Missed Peak): {avg_left_eod:.2f}")

deep_dive_2025_2026('NIFTY')
