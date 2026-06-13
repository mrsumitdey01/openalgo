"""
3-YEAR MINUTE-LEVEL FORENSIC BACKTEST -- Bot 4 (Nifty Short Straddle)
=====================================================================
Tracks EVERY trade at 1-minute resolution:
  - Entry price, time, qty
  - Each SL leg hit: time, spot price, leg PnL
  - Peak MTM: time and value
  - MTM trail trigger: if fired, when and where
  - Exit: time, reason, final PnL
  - Intraday spot range (high - low)
  - Post-SL-hit reversal: did spot reverse after hitting the SL?

Produces:
  1. Year-by-year summary (net of charges)
  2. Complete loss trade log with patterns
  3. Pattern frequency table
  4. Actionable pattern diagnosis
"""
import pandas as pd
import duckdb
from datetime import datetime, time as time_obj

DB_PATH = 'db/historify.duckdb'

# --- Charge calculator (exact statutory) -------------------------------------
def calc_charges(spot_price, qty):
    """
    Accurate statutory charges for NSE Options (4-order straddle):
    - Brokerage: Rs.20 x 4 orders = Rs.80
    - STT: 0.1% on sell premium (2 sell orders)
    - Exchange Txn: 0.03503% on total turnover
    - SEBI: 0.0001% on total turnover
    - Stamp: 0.003% on buy premium (2 buy orders)
    - GST: 18% on (brokerage + txn + sebi)
    Using 1% of spot as proxy for each leg's premium.
    """
    premium_per_leg = spot_price * 0.01
    sell_turnover = premium_per_leg * qty * 2   # CE + PE sell legs
    buy_turnover  = premium_per_leg * qty * 2   # CE + PE buy legs (closing)
    total_turnover = sell_turnover + buy_turnover

    brokerage = 80.0
    stt       = sell_turnover * 0.001
    txn       = total_turnover * 0.0003503
    sebi      = total_turnover * 0.000001
    stamp     = buy_turnover * 0.00003
    gst       = (brokerage + txn + sebi) * 0.18
    return brokerage + stt + txn + sebi + stamp + gst


# --- Main backtest engine -----------------------------------------------------
def run(symbol, years=(2023, 2024, 2025, 2026)):
    con = duckdb.connect(DB_PATH)
    df_all = con.execute(f"""
        SELECT timestamp, open, high, low, close
        FROM market_data WHERE symbol='{symbol}'
        ORDER BY timestamp ASC
    """).df()
    df_all['dt'] = pd.to_datetime(df_all['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df_all.set_index('dt', inplace=True)
    df_all = df_all[df_all.index.year.isin(years)]

    grouped = df_all.groupby(df_all.index.date)

    CAPITAL       = 800_000.0
    GAP_PCT       = 0.005      # >0.5% gap → skip day
    SL_PCT        = 0.005      # 0.5% spot proxy SL per leg
    MTM_START     = 0.0025     # 0.25% of capital = Rs.2000 before trail activates
    MTM_TRAIL_DD  = 0.50       # trail fires when MTM drops 50% from peak

    yearly = {}
    all_trades = []            # full trade-level log
    prev_close = None

    for date, day_df in grouped:
        yr = date.year
        if yr not in yearly:
            yearly[yr] = dict(traded=0, skipped_gap=0, wins=0, losses=0,
                              total_pnl=0.0, total_charges=0.0,
                              peak_equity=0.0, max_dd=0.0,
                              win_pnls=[], loss_pnls=[])

        if len(day_df) < 200:           # short/holiday session
            if len(day_df) > 0:
                prev_close = float(day_df.iloc[-1]['close'])
            continue

        day_open  = float(day_df.iloc[0]['open'])
        day_close = float(day_df.iloc[-1]['close'])

        if prev_close is None:
            prev_close = day_close
            continue

        # Gap filter
        gap = abs(day_open - prev_close) / prev_close
        if gap > GAP_PCT:
            yearly[yr]['skipped_gap'] += 1
            prev_close = day_close
            continue

        # Wednesday: half qty (reduce gamma risk)
        base_qty = 65
        qty = 32 if date.weekday() == 2 else base_qty

        # -- Intraday loop --------------------------------------------------
        ce_entry = pe_entry = None
        ce_sl    = pe_sl    = None
        ce_open  = pe_open  = False
        entered  = aborted  = False

        peak_mtm      = 0.0
        peak_mtm_time = None
        day_pnl       = 0.0

        ce_sl_hit_time = None    # minute CE SL was hit
        pe_sl_hit_time = None    # minute PE SL was hit
        ce_sl_hit_price = None
        pe_sl_hit_price = None
        ce_pnl_at_sl_hit = 0.0  # PE leg unrealized when CE SL hit
        spot_after_ce_sl  = []  # spot prices in 30 min after CE SL hit
        exit_reason = 'EOD'

        day_high = float(day_df['high'].max())
        day_low  = float(day_df['low'].min())

        for idx, row in day_df.iterrows():
            t     = idx.time()
            price = float(row['close'])

            # -- Entry: 09:21 candle --------------------------------------
            if t.hour == 9 and t.minute == 21 and not entered:
                ce_entry = pe_entry = price
                ce_sl   = price * (1 + SL_PCT)
                pe_sl   = price * (1 - SL_PCT)
                ce_open = pe_open = True
                entered = True
                continue

            if not entered or aborted:
                continue

            # -- Compute live MTM -----------------------------------------
            ce_mtm = (ce_entry - price) * 0.5 * qty if ce_open else 0.0
            pe_mtm = (price - pe_entry) * 0.5 * qty if pe_open else 0.0
            live_mtm = day_pnl + ce_mtm + pe_mtm

            if live_mtm > peak_mtm:
                peak_mtm      = live_mtm
                peak_mtm_time = t

            # -- Track spot prices after CE SL hit (for reversal analysis) -
            if ce_sl_hit_time is not None and pe_open:
                elapsed = (t.hour * 60 + t.minute) - (ce_sl_hit_time.hour * 60 + ce_sl_hit_time.minute)
                if 0 < elapsed <= 30:
                    spot_after_ce_sl.append(price)

            # -- CE SL check -----------------------------------------------
            if ce_open and price >= ce_sl:
                ce_open = False
                pnl_ce  = (ce_entry - ce_sl) * 0.5 * qty
                day_pnl += pnl_ce
                ce_sl_hit_time  = t
                ce_sl_hit_price = price
                ce_pnl_at_sl_hit = (price - pe_entry) * 0.5 * qty  # PE unrealized at this instant

            # -- PE SL check -----------------------------------------------
            if pe_open and price <= pe_sl:
                pe_open = False
                pnl_pe  = (pe_entry - pe_sl) * 0.5 * qty
                day_pnl += pnl_pe
                pe_sl_hit_time  = t
                pe_sl_hit_price = price

            # -- MTM trailing stop -----------------------------------------
            if peak_mtm > CAPITAL * MTM_START:
                if live_mtm < peak_mtm * (1 - MTM_TRAIL_DD):
                    aborted = True
                    exit_reason = 'MTM_Trail'
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                    ce_open = pe_open = False

            # -- Hard max-loss stop ----------------------------------------
            if live_mtm < -(CAPITAL * 0.02):
                aborted = True
                exit_reason = 'Max_Loss'
                day_pnl  = -(CAPITAL * 0.02)
                ce_open  = pe_open = False

            # -- EOD square-off --------------------------------------------
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

        # -- Classify the trade --------------------------------------------
        intraday_range_pct = (day_high - day_low) / ce_entry * 100

        # Post-CE-SL reversal: did spot come back to CE entry within 30 min?
        reversal_after_ce_sl = False
        if spot_after_ce_sl:
            min_after = min(spot_after_ce_sl)
            if min_after < ce_entry:    # spot reversed below entry → CE leg would have been fine
                reversal_after_ce_sl = True

        both_sl_hit   = (ce_sl_hit_time is not None and pe_sl_hit_time is not None)
        only_ce_hit   = (ce_sl_hit_time is not None and pe_sl_hit_time is None)
        only_pe_hit   = (pe_sl_hit_time is not None and ce_sl_hit_time is None)

        # Pattern classification
        if net_pnl >= 0:
            if both_sl_hit:
                pattern = 'WIN_ONE_LEG_SAVED'
            elif exit_reason == 'MTM_Trail':
                pattern = 'WIN_MTM_TRAIL'
            else:
                pattern = 'WIN_CLEAN'
        else:  # losing day
            if exit_reason == 'Max_Loss':
                pattern = 'LOSS_MAX_LOSS_HIT'
            elif both_sl_hit:
                pattern = 'LOSS_BOTH_SL'         # catastrophic trend day
            elif only_ce_hit and reversal_after_ce_sl:
                pattern = 'LOSS_CE_WHIPSAW'       # CE SL hit, spot reversed → unnecessary loss
            elif only_pe_hit:
                pattern = 'LOSS_PE_WHIPSAW'
            elif only_ce_hit and not reversal_after_ce_sl:
                pattern = 'LOSS_CE_TREND'         # CE SL hit, spot kept going up
            elif exit_reason == 'MTM_Trail':
                pattern = 'LOSS_MTM_TRAIL_EARLY'  # trail fired too early
            else:
                pattern = 'LOSS_CHARGES_ONLY'     # flat day, just lost charges

        # Record
        rec = {
            'date': date,
            'year': yr,
            'dow': date.strftime('%a'),
            'qty': qty,
            'entry': round(ce_entry, 1),
            'day_range_pct': round(intraday_range_pct, 2),
            'peak_mtm': round(peak_mtm, 0),
            'peak_time': str(peak_mtm_time) if peak_mtm_time else '-',
            'ce_sl_time': str(ce_sl_hit_time) if ce_sl_hit_time else '-',
            'pe_sl_time': str(pe_sl_hit_time) if pe_sl_hit_time else '-',
            'reversal_after_ce_sl': reversal_after_ce_sl,
            'exit_reason': exit_reason,
            'gross_pnl': round(day_pnl, 0),
            'charges': round(charges, 0),
            'net_pnl': round(net_pnl, 0),
            'pattern': pattern,
        }
        all_trades.append(rec)

        # Year stats
        yearly[yr]['traded'] += 1
        yearly[yr]['total_charges'] += charges
        yearly[yr]['total_pnl'] += net_pnl
        if yearly[yr]['total_pnl'] > yearly[yr]['peak_equity']:
            yearly[yr]['peak_equity'] = yearly[yr]['total_pnl']
        dd = yearly[yr]['peak_equity'] - yearly[yr]['total_pnl']
        if dd > yearly[yr]['max_dd']:
            yearly[yr]['max_dd'] = dd
        if net_pnl > 0:
            yearly[yr]['wins'] += 1
            yearly[yr]['win_pnls'].append(net_pnl)
        else:
            yearly[yr]['losses'] += 1
            yearly[yr]['loss_pnls'].append(net_pnl)

    return yearly, all_trades


# --- Report -------------------------------------------------------------------
def print_report(yearly, all_trades):
    df = pd.DataFrame(all_trades)

    print("=" * 72)
    print("  3-YEAR MINUTE-LEVEL FORENSIC BACKTEST -- Nifty Bot 4")
    print("  With EXACT Statutory Charges (Brokerage+STT+Txn+GST+Stamp)")
    print("=" * 72)

    total_net = 0
    for yr, s in sorted(yearly.items()):
        traded = s['traded']
        if traded == 0:
            continue
        wr   = s['wins'] / traded * 100
        avgw = sum(s['win_pnls'])  / len(s['win_pnls'])  if s['win_pnls']  else 0
        avgl = sum(s['loss_pnls']) / len(s['loss_pnls']) if s['loss_pnls'] else 0
        total_net += s['total_pnl']
        print(f"\n[{yr}] NET PnL: Rs.{s['total_pnl']:,.0f}  |  Charges: Rs.{s['total_charges']:,.0f}")
        print(f"  Traded: {traded}  Gap-Skipped: {s['skipped_gap']}")
        print(f"  Win Rate: {wr:.1f}%  ({s['wins']}W / {s['losses']}L)")
        print(f"  Avg Win: Rs.{avgw:,.0f}  |  Avg Loss: Rs.{avgl:,.0f}")
        print(f"  Max Drawdown: Rs.{s['max_dd']:,.0f}")

    print(f"\n{'='*72}")
    print(f"  3-YEAR TOTAL NET: Rs.{total_net:,.0f}")
    print(f"{'='*72}")

    # -- Pattern frequency ----------------------------------------------------
    print("\n\n-- PATTERN FREQUENCY (all years) ---------------------------------------")
    pat_counts = df.groupby('pattern').agg(
        Count=('net_pnl', 'count'),
        Avg_PnL=('net_pnl', 'mean'),
        Total_PnL=('net_pnl', 'sum'),
    ).sort_values('Count', ascending=False)
    print(pat_counts.to_string())

    # -- Losing days detail ---------------------------------------------------
    losses = df[df['net_pnl'] < 0].copy()
    print(f"\n\n-- ALL {len(losses)} LOSING DAYS (minute-level) --------------------------")
    print(f"{'Date':<12} {'DOW':<4} {'Net':>7} {'Peak':>6} {'PkTime':<8} {'CE_SL':<8} "
          f"{'PE_SL':<8} {'Rev':>4} {'Range%':>7} {'Pattern'}")
    print("-" * 90)
    for _, r in losses.sort_values('net_pnl').iterrows():
        rev = 'YES' if r['reversal_after_ce_sl'] else 'no'
        print(f"{str(r['date']):<12} {r['dow']:<4} {r['net_pnl']:>7,.0f} "
              f"{r['peak_mtm']:>6,.0f} {r['peak_time']:<8} {r['ce_sl_time']:<8} "
              f"{r['pe_sl_time']:<8} {rev:>4} {r['day_range_pct']:>6.2f}%  {r['pattern']}")

    # -- Pattern-specific analysis ---------------------------------------------
    print("\n\n-- WHIPSAW ANALYSIS (CE_SL hit then spot reversed) ----------------------")
    whip = df[df['pattern'] == 'LOSS_CE_WHIPSAW']
    print(f"  Count: {len(whip)}")
    if len(whip) > 0:
        print(f"  Avg Loss: Rs.{whip['net_pnl'].mean():,.0f}")
        print(f"  Avg Range on those days: {whip['day_range_pct'].mean():.2f}%")
        print(f"  CE SL hit times: {sorted(whip['ce_sl_time'].tolist())}")

    print("\n-- CHARGES-ONLY LOSSES (flat day, no SL hit) ---------------------------")
    flat = df[df['pattern'] == 'LOSS_CHARGES_ONLY']
    print(f"  Count: {len(flat)}  |  Total lost to charges: Rs.{flat['net_pnl'].sum():,.0f}")
    print(f"  Avg range on flat days: {flat['day_range_pct'].mean():.2f}%")
    if len(flat) > 0:
        print(f"  Day distribution: {flat['dow'].value_counts().to_dict()}")

    print("\n-- TREND DAY LOSSES (both SL hit OR CE trend) --------------------------")
    trend = df[df['pattern'].isin(['LOSS_BOTH_SL', 'LOSS_CE_TREND', 'LOSS_PE_WHIPSAW'])]
    print(f"  Count: {len(trend)}")
    if len(trend) > 0:
        print(f"  Avg Loss: Rs.{trend['net_pnl'].mean():,.0f}")
        print(f"  Avg Range: {trend['day_range_pct'].mean():.2f}%")
        for _, r in trend.iterrows():
            print(f"  {r['date']} ({r['dow']}) | Net={r['net_pnl']:.0f} | "
                  f"Range={r['day_range_pct']:.2f}% | {r['pattern']}")

    print("\n-- MTM TRAIL ANALYSIS --------------------------------------------------")
    trail_days = df[df['exit_reason'] == 'MTM_Trail']
    trail_win  = trail_days[trail_days['net_pnl'] >= 0]
    trail_loss = trail_days[trail_days['net_pnl'] < 0]
    print(f"  MTM Trail fired: {len(trail_days)} days")
    print(f"  Trail fired and profitable: {len(trail_win)}  |  Trail fired and still lost: {len(trail_loss)}")
    if len(trail_days) > 0:
        print(f"  Avg PnL when trail fired: Rs.{trail_days['net_pnl'].mean():,.0f}")
        print(f"  Avg peak before trail: Rs.{trail_days['peak_mtm'].mean():,.0f}")

    # -- Winning days insight -------------------------------------------------
    wins = df[df['net_pnl'] > 0]
    print(f"\n-- WINNING DAYS INSIGHT ------------------------------------------------")
    print(f"  Total winning days: {len(wins)}")
    print(f"  Avg range on winning days: {wins['day_range_pct'].mean():.2f}%")
    big_wins = wins[wins['net_pnl'] > 8000]
    print(f"  Big wins (>Rs.8000): {len(big_wins)}  |  Avg: Rs.{big_wins['net_pnl'].mean():,.0f}")

    return df


if __name__ == '__main__':
    print("Running 3-year minute-level forensic backtest on NIFTY...")
    yearly, trades = run('NIFTY')
    df = print_report(yearly, trades)
    df.to_csv('scratch/trade_log_3yr.csv', index=False)
    print("\n[OK] Full trade log saved to scratch/trade_log_3yr.csv")
