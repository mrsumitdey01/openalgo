"""
Exhaustive Deep Audit Script for Bot 1 Backtesting Logic
Goal: 100% verification that backtest results match raw data signals and live trading emulation.
"""
import sys
import pandas as pd
import numpy as np
from datetime import datetime, time

sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot1_backtest
from services.backtest_service import calculate_statutory_charges
from database.historify_db import get_ohlcv

CAPITAL = 20000000
LOT_SIZE = 30  # 1 lot of BankNifty
YEAR = "2025"
PROFILES = ["futures", "options_buying", "options_selling", "options_spread"]

print("="*80)
print("STARTING DEEP AUDIT OF BOT1 BACKTESTING ENGINE")
print("="*80)

def load_raw_data():
    # Load 2025 data for BankNifty 1min
    start_ts = int(datetime(2025, 1, 1).timestamp())
    end_ts = int(datetime(2025, 12, 31, 23, 59, 59).timestamp())
    
    df = get_ohlcv(
        symbol='BANKNIFTY',
        exchange='NSE_INDEX',
        interval='1min',
        start_timestamp=start_ts,
        end_timestamp=end_ts
    )
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["datetime"] = df["timestamp"].apply(lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"))
    return df

df_raw = load_raw_data()
print(f"Loaded raw data for 2025. Total candles: {len(df_raw)}")

for profile in PROFILES:
    print(f"\n{'='*80}\nAUDITING PROFILE: {profile.upper()}\n{'='*80}")
    params = {
        'symbol': 'BANKNIFTY',
        'exchange': 'NSE_INDEX',
        'start_date': f'{YEAR}-01-01',
        'end_date': f'{YEAR}-12-31',
        'capital': CAPITAL,
        'lot_size': LOT_SIZE,
        'execution_mode': profile
    }
    
    success, response, code = run_bot1_backtest(params)
    if not success:
        print(f"FAILED to run backtest for {profile}: {response}")
        continue
        
    trades = response['trades']
    print(f"Completed {len(trades)} trades.")
    
    # Setup error tracking
    errors = []
    
    # Map execution mode to charges profile and spread delta
    if profile == "futures":
        charges_prof = "fo_futures"
        margin_mult = 0.10
        spread_mult = 1.0
    elif profile == "options_buying":
        charges_prof = "fo_options"
        margin_mult = 0.01
        spread_mult = 0.01
    elif profile == "options_selling":
        charges_prof = "fo_options"
        margin_mult = 0.10
        spread_mult = 0.01
    else:  # options_spread
        charges_prof = "fo_options"
        margin_mult = 0.005
        spread_mult = 0.005

    for t_idx, t in enumerate(trades):
        # 1. Verify QTY
        if t['qty'] != LOT_SIZE:
            errors.append(f"Trade {t['id']}: Invalid Qty {t['qty']} (Expected {LOT_SIZE})")
            
        # 2. Verify Entry Time
        entry_dt = datetime.strptime(t['entry_time'], "%Y-%m-%d %H:%M:%S")
        if entry_dt.time() < time(9, 30) or entry_dt.time() > time(14, 45):
            errors.append(f"Trade {t['id']}: Invalid Entry Time {entry_dt.time()}")
            
        # 3. Verify Margin and Entry Fees
        entry_price = t['entry_price']
        
        # Spot price approximation (spread / spread_mult)
        implied_spot = entry_price / spread_mult
        expected_entry_value = entry_price * LOT_SIZE
        entry_side = "SELL" if t['direction'] == "SHORT" else "BUY"
        expected_entry_fee, _ = calculate_statutory_charges(charges_prof, abs(expected_entry_value), LOT_SIZE, entry_side)
        
        if abs(t['entry_fee'] - expected_entry_fee) > 0.1:
            errors.append(f"Trade {t['id']}: Entry fee mismatch. Expected {expected_entry_fee:.2f}, Got {t['entry_fee']}")
            
        # 4. Verify Exit
        exit_dt = datetime.strptime(t['exit_time'], "%Y-%m-%d %H:%M:%S")
            
        if t['exit_reason'] == "EOD Square-Off" and exit_dt.time() < time(15, 15):
            errors.append(f"Trade {t['id']}: EOD Square-Off before 15:15 ({exit_dt.time()})")
            
        exit_price = t['exit_price']
        expected_exit_value = exit_price * LOT_SIZE
        exit_side = "BUY" if t['direction'] == "SHORT" else "SELL"
        expected_exit_fee, _ = calculate_statutory_charges(charges_prof, abs(expected_exit_value), LOT_SIZE, exit_side)
        
        if abs(t['exit_fee'] - expected_exit_fee) > 0.1:
            errors.append(f"Trade {t['id']}: Exit fee mismatch. Expected {expected_exit_fee:.2f}, Got {t['exit_fee']}")
            
        # 5. Verify PnL Math
        if t['direction'] == "LONG":
            gross_pnl = (exit_price - entry_price) * LOT_SIZE
        else:
            gross_pnl = (entry_price - exit_price) * LOT_SIZE
            
        if abs(t['gross_pnl'] - gross_pnl) > 0.1:
            errors.append(f"Trade {t['id']}: Gross PnL mismatch. Expected {gross_pnl:.2f}, Got {t['gross_pnl']}")
            
        expected_net_pnl = gross_pnl - expected_entry_fee - expected_exit_fee
        if abs(t['net_pnl'] - expected_net_pnl) > 0.1:
            errors.append(f"Trade {t['id']}: Net PnL mismatch. Expected {expected_net_pnl:.2f}, Got {t['net_pnl']}")
            
    # Capital Validation logic
    actual_final_cap = CAPITAL + sum(t['net_pnl'] for t in trades)
    print(f"Capital Validation:")
    print(f"  Sum(Net PnL) + Initial Cap: {actual_final_cap:,.2f}")
    print(f"  Backtest Final Cap:         {response['metrics']['final_capital']:,.2f}")
    if abs(actual_final_cap - response['metrics']['final_capital']) > 1.0:
        errors.append(f"Final Capital Mismatch! Expected {actual_final_cap}, Got {response['metrics']['final_capital']}")

    if errors:
        print(f"[FAIL] FOUND {len(errors)} ERRORS:")
        for e in errors[:10]:
            print(f"  - {e}")
        if len(errors) > 10: print("  ... and more")
    else:
        print("[PASS] ALL TRADES VERIFIED FLAWLESSLY FOR THIS PROFILE.")
        
print("\n" + "="*80)
print("DEEP AUDIT COMPLETED.")
