import pandas as pd
import duckdb
import os
import json
import numpy as np

DB_PATH = 'db/historify.duckdb'
con = duckdb.connect(DB_PATH)

symbols = {
    'NIFTY': {'lot': 65, 'wed_lot': 32},
    'BANKNIFTY': {'lot': 45, 'wed_lot': 22},
    'SENSEX': {'lot': 30, 'wed_lot': 15}
}

CAPITAL = 800_000.0
GAP_PCT = 0.005
MTM_START = 0.0025
MTM_TRAIL_DD = 0.50
SL_PCT = 0.004

def calc_charges(spot_price, qty):
    premium_per_leg = spot_price * 0.01
    turnover = premium_per_leg * qty * 4 # 2 sell, 2 buy
    brokerage = 80.0
    stt = (premium_per_leg * qty * 2) * 0.001
    txn = turnover * 0.0003503
    sebi = turnover * 0.000001
    stamp = (premium_per_leg * qty * 2) * 0.00003
    gst = (brokerage + txn + sebi) * 0.18
    return brokerage + stt + txn + sebi + stamp + gst

results = []

for symbol, info in symbols.items():
    df_all = con.execute(f"SELECT timestamp, open, high, low, close FROM market_data WHERE symbol='{symbol}' ORDER BY timestamp ASC").df()
    df_all['dt'] = pd.to_datetime(df_all['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df_all.set_index('dt', inplace=True)
    df_all = df_all[df_all.index.year.isin((2023, 2024, 2025, 2026))]
    
    grouped = df_all.groupby(df_all.index.date)
    
    days_data = []
    prev_close = None
    for date, day_df in grouped:
        if len(day_df) < 150:
            if len(day_df) > 0:
                prev_close = float(day_df.iloc[-1]['close'])
            continue
            
        day_open = float(day_df.iloc[0]['open'])
        day_close = float(day_df.iloc[-1]['close'])
        
        if prev_close is None:
            prev_close = day_close
            continue
            
        gap = abs(day_open - prev_close) / prev_close
        if gap > GAP_PCT:
            prev_close = day_close
            continue
            
        m30_df = day_df.between_time('09:15', '09:44')
        if m30_df.empty:
            continue
        high_30m = float(m30_df['high'].max())
        low_30m = float(m30_df['low'].min())
        
        days_data.append({
            'date': date,
            'df': day_df,
            'high_30m': high_30m,
            'low_30m': low_30m,
            'close': day_close
        })
        prev_close = day_close

    combos = [
        ("Base", False, False, False),
        ("DR", True, False, False),
        ("IF", False, True, False),
        ("TF", False, False, True),
        ("DR+IF", True, True, False),
        ("DR+TF", True, False, True),
        ("IF+TF", False, True, True),
        ("DR+IF+TF", True, True, True),
    ]

    print(f"Running for {symbol} ({len(days_data)} valid days)...")
    
    for name, use_dr, use_if, use_tf in combos:
        total_pnl = 0.0
        winning_days = 0
        losing_days = 0
        
        for day in days_data:
            df = day['df']
            date = day['date']
            
            qty = info['wed_lot'] if date.weekday() == 2 else info['lot']
            if use_if:
                qty = qty * 3
                
            entry_time = '09:45' if use_tf else '09:21'
            
            ce_open = pe_open = False
            ce_entry = pe_entry = 0
            ce_sl = pe_sl = 0
            
            entered = aborted = False
            day_pnl = 0.0
            peak_mtm = 0.0
            rolls_done = 0
            max_rolls = 1 if use_dr else 0
            
            wings_cost = 0.0
            charges = 0.0
            
            for idx, row in df.iterrows():
                t = idx.time()
                price = float(row['close'])
                
                if not entered and (t.hour == int(entry_time[:2]) and t.minute >= int(entry_time[3:])):
                    entered = True
                    charges = calc_charges(price, qty)
                    
                    if use_if:
                        wings_cost = (price * 0.01 * 0.30) * qty * 2
                    
                    if use_tf:
                        if price > day['high_30m']:
                            pe_entry = price
                            pe_sl = price * (1 - SL_PCT)
                            pe_open = True
                        elif price < day['low_30m']:
                            ce_entry = price
                            ce_sl = price * (1 + SL_PCT)
                            ce_open = True
                        else:
                            ce_entry = pe_entry = price
                            ce_sl = price * (1 + SL_PCT)
                            pe_sl = price * (1 - SL_PCT)
                            ce_open = pe_open = True
                    else:
                        ce_entry = pe_entry = price
                        ce_sl = price * (1 + SL_PCT)
                        pe_sl = price * (1 - SL_PCT)
                        ce_open = pe_open = True
                    continue

                if not entered or aborted:
                    continue
                    
                ce_mtm = (ce_entry - price) * 0.5 * qty if ce_open else 0.0
                pe_mtm = (price - pe_entry) * 0.5 * qty if pe_open else 0.0
                live_mtm = day_pnl + ce_mtm + pe_mtm - wings_cost
                
                if live_mtm > peak_mtm:
                    peak_mtm = live_mtm
                    
                if ce_open and price >= ce_sl:
                    ce_open = False
                    day_pnl += (ce_entry - ce_sl) * 0.5 * qty
                    if rolls_done < max_rolls:
                        if pe_open:
                            day_pnl += (price - pe_entry) * 0.5 * qty
                        pe_entry = price
                        pe_sl = price * (1 - SL_PCT)
                        pe_open = True
                        rolls_done += 1
                        charges += calc_charges(price, qty)/2
                    elif not pe_open:
                        aborted = True
                        
                if pe_open and price <= pe_sl:
                    pe_open = False
                    day_pnl += (pe_entry - pe_sl) * 0.5 * qty
                    if rolls_done < max_rolls:
                        if ce_open:
                            day_pnl += (ce_entry - price) * 0.5 * qty
                        ce_entry = price
                        ce_sl = price * (1 + SL_PCT)
                        ce_open = True
                        rolls_done += 1
                        charges += calc_charges(price, qty)/2
                    elif not ce_open:
                        aborted = True

                if not aborted and peak_mtm > CAPITAL * MTM_START:
                    if live_mtm < peak_mtm * (1 - MTM_TRAIL_DD):
                        aborted = True
                        if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                        if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                        ce_open = pe_open = False
                        
                if not aborted and live_mtm < -(CAPITAL * 0.02):
                    aborted = True
                    day_pnl = -(CAPITAL * 0.02) + wings_cost
                    ce_open = pe_open = False
                    
                if not aborted and t.hour == 15 and t.minute >= 15:
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False
                    aborted = True

            if not entered:
                continue
                
            net_day_pnl = day_pnl - wings_cost - charges
            total_pnl += net_day_pnl
            if net_day_pnl > 0:
                winning_days += 1
            else:
                losing_days += 1
                
        trades_count = winning_days + losing_days
        win_rate = (winning_days / trades_count) * 100 if trades_count > 0 else 0
        
        results.append({
            'Index': symbol,
            'Combo': name,
            'Win Rate': f"{win_rate:.1f}%",
            'Net PnL': f"Rs.{total_pnl:,.0f}",
            'Trades': trades_count,
            'RawPnL': total_pnl,
            'RawWin': win_rate
        })
        print(f"  [{name}] WR={win_rate:.1f}% | PnL=Rs.{total_pnl:,.0f}")

df_res = pd.DataFrame(results)
df_res = df_res.sort_values(by=['Index', 'RawPnL'], ascending=[True, False])
df_res.drop(columns=['RawPnL', 'RawWin'], inplace=True)
df_res.to_markdown("scratch/combo_results.md", index=False)
