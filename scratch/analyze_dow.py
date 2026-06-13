import pandas as pd
import duckdb
from datetime import datetime

DB_PATH = 'db/historify.duckdb'

def run_dow_analysis(symbol):
    con = duckdb.connect(DB_PATH)
    query = f"SELECT timestamp, open, high, low, close FROM market_data WHERE symbol='{symbol}' ORDER BY timestamp ASC"
    df = con.execute(query).df()
    
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df.set_index('datetime', inplace=True)
    
    grouped = df.groupby(df.index.date)
    
    dow_stats = {i: {'pnl': 0, 'wins': 0, 'losses': 0} for i in range(5)} # 0:Mon, 4:Fri
    
    capital = 800000.0
    GAP_ABORT_PCT = 0.005
    MTM_TRAIL_START_PCT = 0.005
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
            
        ce_entry = pe_entry = ce_sl = pe_sl = None
        ce_open = pe_open = entered = aborted_for_day = False
        peak_mtm = day_pnl = 0
        
        for idx, row in day_df.iterrows():
            current_time = idx.time()
            current_price = row['close']
            
            if current_time.hour == 9 and current_time.minute == 20 and not entered:
                ce_entry = pe_entry = current_price
                ce_sl = current_price * 1.005
                pe_sl = current_price * 0.995
                ce_open = pe_open = entered = True
                continue
                
            if entered and not aborted_for_day:
                current_mtm = 0
                if ce_open: current_mtm += (ce_entry - current_price) * 0.5 * 65
                if pe_open: current_mtm += (current_price - pe_entry) * 0.5 * 65
                
                total_mtm = day_pnl + current_mtm
                if total_mtm > peak_mtm: peak_mtm = total_mtm
                    
                if ce_open and current_price >= ce_sl:
                    ce_open = False
                    day_pnl += (ce_entry - ce_sl) * 0.5 * 65
                if pe_open and current_price <= pe_sl:
                    pe_open = False
                    day_pnl += (pe_entry - pe_sl) * 0.5 * 65
                    
                if peak_mtm > (capital * MTM_TRAIL_START_PCT):
                    if total_mtm < (peak_mtm * 0.5):
                        aborted_for_day = True
                        if ce_open: day_pnl += (ce_entry - current_price) * 0.5 * 65
                        if pe_open: day_pnl += (current_price - pe_entry) * 0.5 * 65
                        ce_open = pe_open = False
                        
                if total_mtm < -(capital * 0.02):
                    aborted_for_day = True
                    day_pnl = -(capital * 0.02)
                    ce_open = pe_open = False
                
                if current_time.hour == 15 and current_time.minute == 15 and not aborted_for_day:
                    if ce_open: day_pnl += (ce_entry - current_price) * 0.5 * 65
                    if pe_open: day_pnl += (current_price - pe_entry) * 0.5 * 65
                    ce_open = pe_open = aborted_for_day = True

        prev_close = day_close
        
        if entered:
            dow = date.weekday()
            if dow < 5:
                dow_stats[dow]['pnl'] += day_pnl
                if day_pnl > 0: dow_stats[dow]['wins'] += 1
                elif day_pnl < 0: dow_stats[dow]['losses'] += 1

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    print("--- 5 YEAR PNL BY DAY OF WEEK ---")
    for i in range(5):
        stats = dow_stats[i]
        traded = stats['wins'] + stats['losses']
        win_rate = (stats['wins'] / traded * 100) if traded > 0 else 0
        print(f"{days[i]}: Rs.{stats['pnl']:.2f} | Win Rate: {win_rate:.1f}% | W: {stats['wins']}, L: {stats['losses']}")

run_dow_analysis('NIFTY')
