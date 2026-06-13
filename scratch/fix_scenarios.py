"""
VERIFIED FIX SIMULATION
Implements 3 data-proven fixes:

FIX 1 — Break-Even Lock (BE Lock):
  Once intraday MTM peak hits Rs.800+, lock a floor at Rs.0 (break-even).
  If MTM falls back below Rs.0, exit.
  WHY: 49 of 67 trend-loss days peaked >Rs.200 before turning negative.
  Avg peak was Rs.846. Locking at Rs.0 once Rs.800 hit = saves those 49 days.

FIX 2 — Tighten CE SL to 0.4% (from 0.5%):
  When CE SL at 0.5% is hit, PE still has big exposure.
  Tighter SL = smaller loss per hit leg, but need to verify it doesn't hurt wins.

FIX 3 — Double-SL after break-even:
  Once BE lock activated AND market moves further against one leg,
  exit the other leg too (full exit) vs holding remaining.
  WHY: On CE trend days the remaining PE leg often continues to lose (spot keeps rising).

We test each fix independently AND combined.
"""
import pandas as pd
import duckdb
from datetime import datetime, time as time_obj

DB_PATH = 'db/historify.duckdb'

def calc_charges(spot_price, qty):
    premium_per_leg = spot_price * 0.01
    sell_turnover = premium_per_leg * qty * 2
    buy_turnover = premium_per_leg * qty * 2
    total_turnover = sell_turnover + buy_turnover
    brokerage = 80.0
    stt = sell_turnover * 0.001
    txn = total_turnover * 0.0003503
    sebi = total_turnover * 0.000001
    stamp = buy_turnover * 0.00003
    gst = (brokerage + txn + sebi) * 0.18
    return brokerage + stt + txn + sebi + stamp + gst


def run_scenario(years, sl_pct, be_lock_trigger, be_lock_floor, exit_other_on_sl, label):
    """
    sl_pct: spot proxy SL (0.005 = 0.5%)
    be_lock_trigger: once peak_mtm hits this, activate lock
    be_lock_floor: if active, exit when mtm < this
    exit_other_on_sl: after CE SL hit, also exit PE if MTM < floor?
    """
    con = duckdb.connect(DB_PATH)
    df_all = con.execute("""
        SELECT timestamp, open, high, low, close
        FROM market_data WHERE symbol='NIFTY'
        ORDER BY timestamp ASC
    """).df()
    df_all['dt'] = pd.to_datetime(df_all['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df_all.set_index('dt', inplace=True)
    df_all = df_all[df_all.index.year.isin(years)]

    grouped = df_all.groupby(df_all.index.date)

    CAPITAL = 800_000.0
    GAP_PCT = 0.005
    MTM_START = 0.0025
    MTM_TRAIL_DD = 0.50

    total_pnl = 0.0
    wins = losses = 0
    peak_equity = max_dd = 0.0
    prev_close = None

    for date, day_df in grouped:
        if len(day_df) < 200:
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

        qty = 32 if date.weekday() == 2 else 65

        ce_entry = pe_entry = None
        ce_sl = pe_sl = None
        ce_open = pe_open = False
        entered = aborted = False

        peak_mtm = 0.0
        day_pnl = 0.0
        be_locked = False

        for idx, row in day_df.iterrows():
            t = idx.time()
            price = float(row['close'])

            if t.hour == 9 and t.minute == 21 and not entered:
                ce_entry = pe_entry = price
                ce_sl = price * (1 + sl_pct)
                pe_sl = price * (1 - sl_pct)
                ce_open = pe_open = True
                entered = True
                continue

            if not entered or aborted:
                continue

            ce_mtm = (ce_entry - price) * 0.5 * qty if ce_open else 0.0
            pe_mtm = (price - pe_entry) * 0.5 * qty if pe_open else 0.0
            live_mtm = day_pnl + ce_mtm + pe_mtm

            if live_mtm > peak_mtm:
                peak_mtm = live_mtm

            # Activate BE lock once peak hits trigger
            if be_lock_trigger and peak_mtm >= be_lock_trigger and not be_locked:
                be_locked = True

            # BE lock exit: if locked and MTM falls below floor, exit all
            if be_locked and live_mtm < be_lock_floor and not aborted:
                aborted = True
                if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                ce_open = pe_open = False

            # CE SL
            if ce_open and price >= ce_sl:
                ce_open = False
                day_pnl += (ce_entry - ce_sl) * 0.5 * qty
                # If exit_other_on_sl and PE is underwater too, exit PE also
                if exit_other_on_sl and pe_open:
                    pe_live = (price - pe_entry) * 0.5 * qty
                    if day_pnl + pe_live < 0:
                        day_pnl += (price - pe_entry) * 0.5 * qty
                        pe_open = False

            # PE SL
            if pe_open and price <= pe_sl:
                pe_open = False
                day_pnl += (pe_entry - pe_sl) * 0.5 * qty

            # MTM trail
            if peak_mtm > CAPITAL * MTM_START:
                if live_mtm < peak_mtm * (1 - MTM_TRAIL_DD):
                    aborted = True
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False

            # Max loss
            if live_mtm < -(CAPITAL * 0.02):
                aborted = True
                day_pnl = -(CAPITAL * 0.02)
                ce_open = pe_open = False

            # EOD
            if t.hour == 15 and t.minute == 15 and not aborted:
                if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                ce_open = pe_open = False
                aborted = True

        prev_close = day_close
        if not entered:
            continue

        charges = calc_charges(ce_entry, qty)
        net_pnl = day_pnl - charges
        total_pnl += net_pnl
        if total_pnl > peak_equity: peak_equity = total_pnl
        dd = peak_equity - total_pnl
        if dd > max_dd: max_dd = dd
        if net_pnl > 0: wins += 1
        else: losses += 1

    traded = wins + losses
    wr = wins / traded * 100 if traded > 0 else 0
    return dict(label=label, pnl=total_pnl, wins=wins, losses=losses, wr=wr, max_dd=max_dd, traded=traded)


YEARS = (2023, 2024, 2025, 2026)

configs = [
    # (sl_pct, be_lock_trigger, be_lock_floor, exit_other_on_sl, label)
    (0.005, None,  None,  False, 'BASELINE (current)'),
    (0.005, 800,   0,     False, 'FIX1: BE Lock @800 -> floor 0'),
    (0.005, 1000,  0,     False, 'FIX1b: BE Lock @1000 -> floor 0'),
    (0.005, 1500,  0,     False, 'FIX1c: BE Lock @1500 -> floor 0'),
    (0.005, 800,   0,     True,  'FIX1+FIX3: BE Lock + exit PE on CE SL'),
    (0.004, None,  None,  False, 'FIX2: Tighter SL 0.4%'),
    (0.006, None,  None,  False, 'FIX2b: Wider SL 0.6%'),
    (0.004, 800,   0,     False, 'FIX1+2: Tight SL + BE Lock'),
    (0.005, 800,   -500,  False, 'FIX1 variant: BE Lock @800 -> floor -500'),
    (0.005, 600,   0,     False, 'FIX1 aggressive: BE Lock @600 -> floor 0'),
]

print("=" * 85)
print(f"  3-YEAR (2023-2026) SCENARIO TEST: Which fix actually helps?")
print("=" * 85)
print(f"{'Label':<45} {'Net PnL':>10} {'Wins':>5} {'Loss':>5} {'WinRate':>8} {'MaxDD':>10}")
print("-" * 85)

results = []
for cfg in configs:
    r = run_scenario(YEARS, *cfg)
    results.append(r)
    print(f"{r['label']:<45} {r['pnl']:>10,.0f} {r['wins']:>5} {r['losses']:>5} {r['wr']:>7.1f}% {r['max_dd']:>10,.0f}")

print("=" * 85)

# Find the winner
best = max(results, key=lambda x: x['pnl'])
print(f"\nBEST: {best['label']}")
print(f"  Net PnL: Rs.{best['pnl']:,.0f} vs Baseline: Rs.{results[0]['pnl']:,.0f}")
print(f"  Improvement: Rs.{best['pnl'] - results[0]['pnl']:,.0f}")
print(f"  Win Rate: {best['wr']:.1f}% vs Baseline: {results[0]['wr']:.1f}%")
