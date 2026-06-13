"""
FINAL INSIGHT:
- ALL days baseline: Rs.7.16L profit, 46.6% win rate, 290 trades
- Friday ONLY:       Rs.2.38L profit, 63.5% win rate, 63 trades
- The baseline ALL DAYS is STILL the best total PnL

The SMALL_LOSS_THETA problem is a MODEL ARTEFACT:
Those 136 "losing" days lose only Rs.18-40. That is JUST THE CHARGES.
In reality, our bot generates: ~ -Rs.20 to Rs.5000 per day.
The "losing" is purely a proxy model limitation.

The REAL breakthrough insight:
The ALL DAYS baseline has 155 loss days, but:
- Most "loss days" lose only Rs.20-40 (just charges, no real theta model)
- Real STRUCTURAL losses (>Rs.500) = only 12 WHIPSAW days + 9 REVERSAL days

SOLUTION THAT ACTUALLY WORKS: 
Test different LOSS CUTOFF times.
Currently: No intraday loss cutoff, all exits at 15:15 or SL.
What if: If by 12:00, the straddle is at a loss > Rs.500, EXIT EARLY?
The REVERSAL days typically show: profit at 11:00, then reverse by 15:15.

Let's test: "TIME-BASED DEFENSIVE EXIT" - 
If at 12:30 the trade is still at a loss > Rs.300, exit and save charges.
Combine with: If at 11:00 we are up > Rs.2000, move SL to breakeven (protect profit).
"""
import pandas as pd
import duckdb

DB_PATH = 'db/historify.duckdb'

def run(symbol, use_time_exit, use_be_lock, time_exit_hour, time_exit_min, be_trigger, be_lock_pnl, label):
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
    total_pnl = wins = losses = 0
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

        qty = 65
        if date.weekday() == 2: qty = 32
        ce_entry = pe_entry = None
        ce_sl = pe_sl = None
        ce_open = pe_open = False
        entered = aborted = be_locked = False
        peak_mtm = day_pnl = 0

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
                mtm = 0
                if ce_open: mtm += (ce_entry - price) * 0.5 * qty
                if pe_open: mtm += (price - pe_entry) * 0.5 * qty
                total_mtm = day_pnl + mtm
                if total_mtm > peak_mtm: peak_mtm = total_mtm

                # Break-even lock: once profit > be_trigger, lock SL to be_lock_pnl
                if use_be_lock and not be_locked and total_mtm >= be_trigger:
                    be_locked = True
                    # If market reverses and we drop back to be_lock_pnl, exit
                if use_be_lock and be_locked and total_mtm <= be_lock_pnl:
                    aborted = True
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False

                if ce_open and price >= ce_sl:
                    ce_open = False
                    day_pnl += (ce_entry - ce_sl) * 0.5 * qty
                if pe_open and price <= pe_sl:
                    pe_open = False
                    day_pnl += (pe_entry - pe_sl) * 0.5 * qty

                # MTM trail
                if peak_mtm > (capital * MTM_START) and total_mtm < peak_mtm * 0.5:
                    aborted = True
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False

                # Time-based defensive exit: if losing at checkpoint, cut
                if use_time_exit and t.hour == time_exit_hour and t.minute == time_exit_min:
                    if total_mtm < -300 and not aborted:
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
                    ce_open = pe_open = aborted = True

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
    print(f"{label:<42} {total_pnl:>10,.0f} {wins:>5} {losses:>6} {wr:>7.1f}% {max_dd:>10,.0f}")

print("=" * 82)
print(f"  TIME-BASED & BREAK-EVEN LOCK ANALYSIS (2025-2026, Nifty)")
print("=" * 82)
print(f"{'Scenario':<42} {'Net PnL':>10} {'Wins':>5} {'Loss':>6} {'WinRate':>8} {'MaxDD':>10}")
print("-" * 82)

run('NIFTY', False, False, 0, 0, 0, 0,           'BASELINE (no changes)')
run('NIFTY', True,  False, 12, 0, 0, 0,           'Cut loss @ 12:00 if losing Rs.300')
run('NIFTY', True,  False, 13, 0, 0, 0,           'Cut loss @ 13:00 if losing Rs.300')
run('NIFTY', True,  False, 11, 0, 0, 0,           'Cut loss @ 11:00 if losing Rs.300')
run('NIFTY', False, True,  0, 0, 3000, 1000,      'BE Lock: +3k -> lock at +1k')
run('NIFTY', False, True,  0, 0, 2000, 500,       'BE Lock: +2k -> lock at +500')
run('NIFTY', False, True,  0, 0, 1500, 0,         'BE Lock: +1.5k -> lock at breakeven')
run('NIFTY', True,  True,  12, 0, 2000, 500,      'COMBO: Cut@12 + BE Lock +2k->+500')
run('NIFTY', True,  True,  12, 0, 3000, 1000,     'COMBO: Cut@12 + BE Lock +3k->+1k')

print("=" * 82)
