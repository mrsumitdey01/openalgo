"""
Root-cause forensics on ALL 2025-2026 days:
- Categorize every day into trade patterns
- Identify what TIME the max loss occurs
- Check if re-centering (sell again after big move) would help
- Check if profit target exit (e.g., 50% of day premium) would help
- Check if adding wings (Iron Condor) would cap losses
"""
import pandas as pd
import duckdb
from datetime import datetime

DB_PATH = 'db/historify.duckdb'

def forensics(symbol):
    con = duckdb.connect(DB_PATH)
    df = con.execute(f"""
        SELECT timestamp, open, high, low, close 
        FROM market_data WHERE symbol='{symbol}' ORDER BY timestamp ASC
    """).df()
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df.set_index('datetime', inplace=True)
    df = df[df.index.year >= 2025]
    grouped = df.groupby(df.index.date)

    capital = 800000.0
    GAP_ABORT_PCT = 0.005
    prev_close = None

    # Categorize days
    category_counts = {
        'TREND_DAY_LOSS': 0,       # Strong one-directional move, both SLs hit
        'REVERSAL_AFTER_PROFIT': 0, # Was profitable, reversed EOD
        'WHIPSAW_LOSS': 0,          # Choppy, hit one SL then reversed
        'SMALL_LOSS_THETA': 0,      # Barely lost after charges
        'BIG_WIN': 0,               # Won > 5000
        'SMALL_WIN': 0,             # Won 0-5000
    }
    
    # Analysis for each improvement hypothesis
    profit_target_gains = 0  # Extra gains if we exit at 80% of daily premium collected
    iron_condor_saves = 0    # Losses capped if we bought wings at 1.5%
    recenter_gains = 0       # Extra gains from re-selling after big move

    days_detail = []
    
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

        qty = 65
        if date.weekday() == 2:
            qty = 32

        ce_entry = pe_entry = None
        ce_sl = pe_sl = None
        ce_open = pe_open = False
        entered = False
        peak_mtm = 0
        day_pnl = 0
        aborted = False
        
        ce_hit_time = pe_hit_time = None
        ce_hit_price = pe_hit_price = None
        max_spot_deviation = 0  # how far spot moved from entry
        
        for idx, row in day_df.iterrows():
            t = idx.time()
            price = row['close']

            if t.hour == 9 and t.minute == 21 and not entered:
                ce_entry = pe_entry = price
                ce_sl = price * 1.005
                pe_sl = price * 0.995
                ce_open = pe_open = entered = True
                continue

            if entered and not aborted:
                dev = abs(price - ce_entry) / ce_entry
                if dev > max_spot_deviation:
                    max_spot_deviation = dev

                mtm = 0
                if ce_open: mtm += (ce_entry - price) * 0.5 * qty
                if pe_open: mtm += (price - pe_entry) * 0.5 * qty
                total_mtm = day_pnl + mtm
                if total_mtm > peak_mtm: peak_mtm = total_mtm

                if ce_open and price >= ce_sl:
                    ce_open = False
                    day_pnl += (ce_entry - ce_sl) * 0.5 * qty
                    ce_hit_time = t
                    ce_hit_price = price

                if pe_open and price <= pe_sl:
                    pe_open = False
                    day_pnl += (pe_entry - pe_sl) * 0.5 * qty
                    pe_hit_time = t
                    pe_hit_price = price

                if peak_mtm > (capital * 0.0025) and total_mtm < peak_mtm * 0.5:
                    aborted = True
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False

                if total_mtm < -(capital * 0.02):
                    aborted = True
                    day_pnl = -(capital * 0.02)
                    ce_open = pe_open = False

                if t.hour == 15 and t.minute == 15 and not aborted:
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False
                    aborted = True

        prev_close = day_close

        if not entered:
            continue
            
        charges = max(ce_entry * 0.01 * qty * 0.0024, 0)  # rough ~0.24% of premium turnover
        net_pnl = day_pnl - charges

        # Categorize
        both_sl_hit = ce_hit_time is not None and pe_hit_time is not None
        one_sl_hit = (ce_hit_time is not None) != (pe_hit_time is not None)
        
        if net_pnl < -1000 and both_sl_hit:
            cat = 'TREND_DAY_LOSS'
        elif net_pnl < 0 and peak_mtm > 1000:
            cat = 'REVERSAL_AFTER_PROFIT'
        elif net_pnl < 0 and one_sl_hit:
            cat = 'WHIPSAW_LOSS'
        elif net_pnl < 0:
            cat = 'SMALL_LOSS_THETA'
        elif net_pnl > 5000:
            cat = 'BIG_WIN'
        else:
            cat = 'SMALL_WIN'
        
        category_counts[cat] += 1
        
        days_detail.append({
            'Date': date,
            'DOW': ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][date.weekday()],
            'Qty': qty,
            'Entry': ce_entry,
            'Max_Dev': round(max_spot_deviation * 100, 2),
            'Peak_MTM': round(peak_mtm, 0),
            'Net_PnL': round(net_pnl, 0),
            'Category': cat,
            'CE_SL_Time': ce_hit_time,
            'PE_SL_Time': pe_hit_time,
        })
    
    df_d = pd.DataFrame(days_detail)
    
    print("=" * 60)
    print("  2025-2026 FORENSIC TRADE ANALYSIS")
    print("=" * 60)
    
    print("\n--- Day Categories ---")
    total = len(df_d)
    for cat, count in category_counts.items():
        pct = count / total * 100 if total > 0 else 0
        print(f"  {cat:<30}: {count:3d} days ({pct:.1f}%)")
    
    print("\n--- LOSING DAYS IN DETAIL ---")
    losing = df_d[df_d['Net_PnL'] < 0].sort_values('Net_PnL')
    for _, r in losing.iterrows():
        ce_t = str(r['CE_SL_Time']) if r['CE_SL_Time'] else '-'
        pe_t = str(r['PE_SL_Time']) if r['PE_SL_Time'] else '-'
        print(f"  {r['Date']} ({r['DOW']}) | PnL={r['Net_PnL']:7.0f} | Dev={r['Max_Dev']:.2f}% | Peak={r['Peak_MTM']:5.0f} | CE_SL@{ce_t} | PE_SL@{pe_t} | {r['Category']}")

    print("\n--- PROFIT TARGET SIMULATION ---")
    # What if we exit when cumulative PnL for the day hits 60% of expected daily premium?
    # Approximate daily premium: 1% of spot * qty * 2 legs * 50% (theta typically collects half at mid-day)
    # So target = spot * 0.01 * qty * 2 * 0.5 = spot * qty * 0.01
    pt_wins = 0
    pt_losses = 0
    for _, r in df_d.iterrows():
        target = r['Entry'] * 0.01 * r['Qty'] * 0.5  # 50% of one leg's premium
        # If peak_mtm hit the target, assume we'd exit there
        if r['Peak_MTM'] >= target:
            pt_wins += 1
        else:
            if r['Net_PnL'] < 0:
                pt_losses += 1
            else:
                pt_wins += 1
    print(f"  If we exit when +{round(target, 0)} profit target hit:")
    print(f"  Simulated Win Days: {pt_wins} / {total} ({pt_wins/total*100:.1f}%)")
    print(f"  Simulated Loss Days (peak never hit target): {pt_losses}")
    
    print("\n--- MAX SPOT DEVIATION on LOSING DAYS ---")
    for cat in ['TREND_DAY_LOSS', 'WHIPSAW_LOSS', 'REVERSAL_AFTER_PROFIT', 'SMALL_LOSS_THETA']:
        sub = df_d[df_d['Category'] == cat]
        if len(sub) > 0:
            print(f"  {cat}: Avg Move = {sub['Max_Dev'].mean():.2f}% | Max Move = {sub['Max_Dev'].max():.2f}%")
    
    print("\n--- PROFITABLE DAYS SUMMARY ---")
    winning = df_d[df_d['Net_PnL'] > 0]
    print(f"  Avg profit on winning days: Rs.{winning['Net_PnL'].mean():.0f}")
    print(f"  Avg spot move on winning days: {winning['Max_Dev'].mean():.2f}%")
    print(f"  Avg spot move on LOSING days: {df_d[df_d['Net_PnL']<0]['Max_Dev'].mean():.2f}%")

forensics('NIFTY')
