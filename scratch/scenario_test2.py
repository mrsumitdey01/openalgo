"""
DEEP INSIGHT from scenario test:
- Wider SL HURTS (loses 55k vs baseline) - current 0.5% SL is already optimal
- Profit target does nothing meaningful for net PnL
- Skip Wednesday improves win RATE slightly but LOSES 47k of net profit

The REAL problem now revealed:
136 days of SMALL_LOSS_THETA = just paying charges with no theta gain.
These happen when BOTH spots move < 0.4% (no one leg hits SL and no theta collected).

The root cause: we are using SPOT price as proxy for OPTIONS premium.
In reality, at 9:21 AM the option has HIGH IV. By 12:00, IV crush = massive theta.
The SPOT barely moved but the OPTIONS PREMIUM CRUSHED.

So the correct model is:
- Premium collected (our profit) decays as: premium * (1 - time_fraction^0.5) — square root of time
- If spot moves 0 and we hold till 15:15, we collect ~70-80% of premium
- These "SMALL_LOSS_THETA" are actually WINNING days with our CURRENT bot but 
  the backtest OVERESTIMATES how much premium we lose because it simulates spot prices
  not option prices

THE REAL QUESTION IS: What strategy change generates more net profit on days
where spot barely moves? 

SOLUTION: Use a smarter "Theta Scalping" approach:
1. Instead of fixed SL, use a TRAILING CE/PE individually
2. If CE premium drops 70% (spot moved away from CE), close CE early for big profit, ride PE 
3. Only trade Thu/Fri when premium crush is most violent (expiry effect)

Let's test: What if we ONLY trade Thursday + Friday (2 days/week, highest premium crush)?
"""
import pandas as pd
import duckdb

DB_PATH = 'db/historify.duckdb'

def run_scenario(symbol, allowed_days, sl_pct, label):
    """
    allowed_days: list of weekday ints (0=Mon, 4=Fri). None = all days.
    """
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
    MTM_START = 0.0025
    prev_close = None
    total_pnl = 0
    wins = losses = 0
    peak_equity = max_dd = 0
    
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

        # Skip days not in allowed set
        if allowed_days is not None and date.weekday() not in allowed_days:
            prev_close = day_close
            continue

        qty = 65
        ce_entry = pe_entry = None
        ce_sl = pe_sl = None
        ce_open = pe_open = False
        entered = False
        peak_mtm = day_pnl = 0
        aborted = False

        for idx, row in day_df.iterrows():
            t = idx.time()
            price = row['close']

            if t.hour == 9 and t.minute == 21 and not entered:
                ce_entry = pe_entry = price
                ce_sl = price * (1 + sl_pct)
                pe_sl = price * (1 - sl_pct)
                ce_open = pe_open = entered = True
                continue

            if entered and not aborted:
                mtm = 0
                if ce_open: mtm += (ce_entry - price) * 0.5 * qty
                if pe_open: mtm += (price - pe_entry) * 0.5 * qty
                total_mtm = day_pnl + mtm
                if total_mtm > peak_mtm: peak_mtm = total_mtm

                if ce_open and price >= ce_sl:
                    ce_open = False
                    day_pnl += (ce_entry - ce_sl) * 0.5 * qty
                if pe_open and price <= pe_sl:
                    pe_open = False
                    day_pnl += (pe_entry - pe_sl) * 0.5 * qty

                if peak_mtm > (capital * MTM_START) and total_mtm < peak_mtm * 0.5:
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
        if not entered: continue

        premium = ce_entry * 0.01 * qty
        brokerage = 80
        stt = premium * 2 * 0.001
        txn = premium * 4 * 0.0003503
        gst = (brokerage + txn) * 0.18
        charges = brokerage + stt + txn + gst

        net_pnl = day_pnl - charges
        total_pnl += net_pnl
        if total_pnl > peak_equity: peak_equity = total_pnl
        dd = peak_equity - total_pnl
        if dd > max_dd: max_dd = dd
        if net_pnl > 0: wins += 1
        else: losses += 1

    traded = wins + losses
    wr = wins / traded * 100 if traded > 0 else 0
    print(f"{label:<35} {total_pnl:>10,.0f} {wins:>6} {losses:>7} {wr:>7.1f}% {max_dd:>10,.0f}")
    return {'pnl': total_pnl, 'wins': wins, 'losses': losses, 'wr': wr, 'max_dd': max_dd}

print("=" * 75)
print(f"  WHICH DAYS TO TRADE? Day-filter analysis (2025-2026)")
print("=" * 75)
print(f"{'Scenario':<35} {'Net PnL':>10} {'Wins':>6} {'Losses':>7} {'WinRate':>8} {'MaxDD':>10}")
print("-" * 75)

run_scenario('NIFTY', None,         0.005, 'ALL Days (baseline)')
run_scenario('NIFTY', [3, 4],       0.005, 'Thu+Fri ONLY')
run_scenario('NIFTY', [0, 1, 3, 4], 0.005, 'Mon+Tue+Thu+Fri (skip Wed)')
run_scenario('NIFTY', [3],          0.005, 'Thursday ONLY')
run_scenario('NIFTY', [4],          0.005, 'Friday ONLY')
run_scenario('NIFTY', [1, 3, 4],    0.005, 'Tue+Thu+Fri')
run_scenario('NIFTY', [0, 3, 4],    0.005, 'Mon+Thu+Fri')

print("=" * 75)
