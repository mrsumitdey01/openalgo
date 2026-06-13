"""
SOLUTION BACKTEST: Test 3 concrete improvements discovered from forensics:

Problem 1: SMALL_LOSS_THETA (136 days, 46.9%) — losing only CHARGES (~Rs.38-40)
  Cause: Spot barely moves, theta barely collects, charges eat the gain.
  FIX: Add a PROFIT TARGET EXIT at 60% of expected daily theta. 
       If Rs.1500 profit is locked by 12:00, exit early, lock the win.
       This converts many "small wins eroded to small loss" days.

Problem 2: WHIPSAW_LOSS (12 days, 4.1%) — one leg hits SL, spot reverses, losing leg too
  Cause: Our SL on spot proxy (0.5%) is too tight. It's being hit by normal intraday noise.
  FIX: Widen the SL slightly from 0.5% to 0.6% spot proxy. This gives the trade 
       more breathing room on whipsaw days.

Problem 3: REVERSAL_AFTER_PROFIT (9 days, 3.1%) — trade profits, then reverses badly EOD
  FIX: The 0.25% MTM trail (already applied) should help. Let's verify.

Also test: Do NOT trade on Wednesday at ALL (instead of half qty).
  Evidence: All Wednesday SMALL_LOSS_THETA days are -Rs.18 to -Rs.20 (just charges, no theta)
            This suggests Wednesday intraday premium is too thin for profitable straddle.
"""
import pandas as pd
import duckdb

DB_PATH = 'db/historify.duckdb'

SCENARIOS = {
    'CURRENT (Baseline)': {
        'sl_pct': 0.005,
        'mtm_start': 0.0025,
        'profit_target': None,  # No profit target
        'skip_wednesday': False,
        'wednesday_skip': False,
    },
    'FIX1: Profit Target Rs.2000': {
        'sl_pct': 0.005,
        'mtm_start': 0.0025,
        'profit_target': 2000,
        'skip_wednesday': False,
    },
    'FIX2: Wider SL (0.6%)': {
        'sl_pct': 0.006,
        'mtm_start': 0.0025,
        'profit_target': None,
        'skip_wednesday': False,
    },
    'FIX3: Skip Wednesdays': {
        'sl_pct': 0.005,
        'mtm_start': 0.0025,
        'profit_target': None,
        'skip_wednesday': True,
    },
    'FIX4: All Combined': {
        'sl_pct': 0.006,
        'mtm_start': 0.0025,
        'profit_target': 2000,
        'skip_wednesday': True,
    },
}

def run_scenario(symbol, cfg):
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
    
    total_pnl = 0
    wins = losses = skipped = 0
    peak_equity = 0
    max_dd = 0

    for date, day_df in grouped:
        if len(day_df) < 300:
            if len(day_df) > 0: prev_close = day_df.iloc[-1]['close']
            continue

        # Skip Wednesday entirely if configured
        if cfg['skip_wednesday'] and date.weekday() == 2:
            prev_close = day_df.iloc[-1]['close']
            skipped += 1
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
        if date.weekday() == 2 and not cfg['skip_wednesday']:
            qty = 32

        ce_entry = pe_entry = None
        ce_sl = pe_sl = None
        ce_open = pe_open = False
        entered = False
        peak_mtm = 0
        day_pnl = 0
        aborted = False

        for idx, row in day_df.iterrows():
            t = idx.time()
            price = row['close']

            if t.hour == 9 and t.minute == 21 and not entered:
                ce_entry = pe_entry = price
                ce_sl = price * (1 + cfg['sl_pct'])
                pe_sl = price * (1 - cfg['sl_pct'])
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

                # MTM Trailing Stop
                if peak_mtm > (capital * cfg['mtm_start']) and total_mtm < peak_mtm * 0.5:
                    aborted = True
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False

                # Profit Target
                if cfg['profit_target'] and total_mtm >= cfg['profit_target'] and not aborted:
                    aborted = True
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False

                # System max loss
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

        # Charges: Brokerage + STT + Transaction + GST
        premium = ce_entry * 0.01 * qty  # ~1% of spot per leg
        brokerage = 80  # 4 orders * Rs.20
        stt = premium * 2 * 0.001  # sell side both legs
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
    win_rate = wins / traded * 100 if traded > 0 else 0
    return {
        'total_pnl': total_pnl,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'max_dd': max_dd,
        'skipped_wed': skipped,
    }

print("=" * 75)
print(f"  2025-2026 SCENARIO COMPARISON: Nifty Short Straddle")
print("=" * 75)
print(f"{'Scenario':<35} {'Net PnL':>10} {'Wins':>6} {'Losses':>7} {'WinRate':>8} {'MaxDD':>10}")
print("-" * 75)

for name, cfg in SCENARIOS.items():
    r = run_scenario('NIFTY', cfg)
    print(f"{name:<35} {r['total_pnl']:>10,.0f} {r['wins']:>6} {r['losses']:>7} {r['win_rate']:>7.1f}% {r['max_dd']:>10,.0f}")

print("=" * 75)
