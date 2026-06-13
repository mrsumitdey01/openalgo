import pandas as pd
import duckdb
import matplotlib.pyplot as plt
from datetime import datetime

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

def generate_graph():
    con = duckdb.connect(DB_PATH)
    df_all = con.execute("""
        SELECT timestamp, open, high, low, close
        FROM market_data WHERE symbol='NIFTY'
        ORDER BY timestamp ASC
    """).df()
    df_all['dt'] = pd.to_datetime(df_all['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df_all.set_index('dt', inplace=True)
    df_all = df_all[df_all.index.year.isin((2023, 2024, 2025, 2026))]

    grouped = df_all.groupby(df_all.index.date)

    CAPITAL = 800_000.0
    GAP_PCT = 0.005
    MTM_START = 0.0025
    MTM_TRAIL_DD = 0.50
    sl_pct = 0.004  # The new optimized SL

    dates = []
    pnls = []
    day_pnl_list = []
    total_pnl = 0.0
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

            # CE SL
            if ce_open and price >= ce_sl:
                ce_open = False
                day_pnl += (ce_entry - ce_sl) * 0.5 * qty

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
        
        dates.append(pd.to_datetime(date))
        pnls.append(total_pnl)
        day_pnl_list.append(net_pnl)

    # Plotting
    plt.figure(figsize=(12, 6))
    
    # Cumulative PnL line
    plt.plot(dates, pnls, label='Cumulative Net PnL (After Charges)', color='#00d1b2', linewidth=2)
    
    # Fill under curve
    plt.fill_between(dates, pnls, 0, where=(pd.Series(pnls) >= 0), alpha=0.3, color='#00d1b2')
    plt.fill_between(dates, pnls, 0, where=(pd.Series(pnls) < 0), alpha=0.3, color='#ff3860')
    
    # Style
    plt.title(f'Bot 4 Verified Performance (2023-2026)\nNet PnL: ₹{total_pnl:,.0f} | Capital: ₹{CAPITAL:,.0f}', fontsize=16, pad=20, color='white')
    plt.xlabel('Date', fontsize=12, color='white')
    plt.ylabel('Net Profit (₹)', fontsize=12, color='white')
    plt.grid(True, linestyle='--', alpha=0.3, color='gray')
    
    # Dark theme
    ax = plt.gca()
    ax.set_facecolor('#1a1a1a')
    plt.gcf().set_facecolor('#1a1a1a')
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('gray')
        
    plt.legend(facecolor='#1a1a1a', labelcolor='white')
    plt.tight_layout()
    plt.savefig('scratch/bot4_verified_graph.png', facecolor='#1a1a1a', dpi=150)
    print("Graph saved to scratch/bot4_verified_graph.png")

if __name__ == '__main__':
    generate_graph()
