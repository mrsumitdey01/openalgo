import sys
import os

# Add project root to path so we can import from strategies
sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')

import pandas as pd
import numpy as np
import duckdb
from strategies.scripts.bot1_hull_dtc_ribbon import HullBBI, DTCRibbon

db_path = r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\db\historify.duckdb'
print(f"Connecting to duckdb at {db_path}...")
con = duckdb.connect(db_path)
print("Loading data...")
df = con.execute("""
    SELECT timestamp as date, open, high, low, close, volume 
    FROM market_data 
    WHERE symbol='BANKNIFTY' 
    ORDER BY timestamp
""").df()
df['date'] = pd.to_datetime(df['date'], unit='s')
df.set_index('date', inplace=True)
df.sort_index(inplace=True)

print(f"Data loaded: {len(df)} rows.")
df_sample = df.copy()

# Compute Indicators using the REAL bot logic
print("Computing Hull BBI & DTC Ribbon (NATIVE)...")
hull = HullBBI()
df_sample = hull.compute(df_sample)

dtc = DTCRibbon()
df_sample = dtc.compute(df_sample)

# Evaluate Signals
df_sample["hma_bullish"] = df_sample["close"] > df_sample["hma"]
df_sample["hma_bearish"] = df_sample["close"] < df_sample["hma"]

df_sample.dropna(inplace=True)
print("Indicators computed.")

def run_diagnostic_backtest(mode):
    trades = []
    current_position = None
    entry_price = 0
    entry_time = None
    stop_level = None
    
    dates = df_sample.index
    closes = df_sample['close'].values
    highs = df_sample['high'].values
    lows = df_sample['low'].values
    
    # SHIFT ALL INDICATORS BY 1 TO SIMULATE `last` IN THE BOT
    hmas = df_sample['hma'].shift(1).values
    hma_bull = df_sample['hma_bullish'].shift(1).values
    hma_bear = df_sample['hma_bearish'].shift(1).values
    rmaxs = df_sample['ribbon_max'].shift(1).values
    rmins = df_sample['ribbon_min'].shift(1).values
    
    # Pre-calculate time logic
    times_hour = np.array([d.hour for d in dates])
    times_minute = np.array([d.minute for d in dates])
    time_val = times_hour * 100 + times_minute # e.g. 1515
    
    print(f"Running simulation for {mode}...")
    
    errors = []

    for i in range(1, len(df_sample)):
        if time_val[i] < 915 or time_val[i] >= 1530:
            continue
            
        c = closes[i]
        h = highs[i]
        l = lows[i]
        hma_val = hmas[i]
        is_hma_bull = hma_bull[i]
        is_hma_bear = hma_bear[i]
        rmax_val = rmaxs[i]
        rmin_val = rmins[i]
        t = time_val[i]
        
        # Skip NaNs from shift
        if np.isnan(hma_val) or np.isnan(rmax_val):
            continue
            
        is_long_cond = (c > hma_val) and is_hma_bull and (c > rmax_val)
        is_short_cond = (c < hma_val) and is_hma_bear and (c < rmin_val)
        
        in_entry_window = (915 <= t <= 1500)
        past_square_off = (t >= 1515)
        
        # 1. Manage Active Position
        if current_position is not None:
            exit_reason = None
            
            # A. Hard Square Off
            if past_square_off:
                exit_reason = "HARD_SQUARE_OFF"
                
            # B. Structural Stop Loss
            elif stop_level is not None:
                if current_position == "LONG" and c < stop_level:
                    exit_reason = "STRUCTURAL_STOP"
                elif current_position == "SHORT" and c > stop_level:
                    exit_reason = "STRUCTURAL_STOP"
                    
            # C. PnL Stop Loss (Mocked via spot movement)
            if not exit_reason:
                pt_diff = (c - entry_price) if current_position == "LONG" else (entry_price - c)
                if pt_diff < -150: # -150 point proxy for PnL Stop
                    exit_reason = "PNL_STOP"
                    
            # D. Signal Reversals
            if not exit_reason:
                if current_position == "LONG":
                    if is_short_cond:
                        exit_reason = "REVERSAL_SHORT"
                    elif is_hma_bear and (c < hma_val - 5.0):
                        exit_reason = "HMA_CROSS_EXIT"
                elif current_position == "SHORT":
                    if is_long_cond:
                        exit_reason = "REVERSAL_LONG"
                    elif is_hma_bull and (c > hma_val + 5.0):
                        exit_reason = "HMA_CROSS_EXIT"
                        
            if exit_reason:
                pnl = (c - entry_price) if current_position == "LONG" else (entry_price - c)
                trades.append({
                    "entry_time": entry_time,
                    "exit_time": dates[i],
                    "type": current_position,
                    "entry_price": entry_price,
                    "exit_price": c,
                    "pnl": pnl,
                    "reason": exit_reason
                })
                
                # Check for flaws
                if exit_reason == "REVERSAL_SHORT" and not is_short_cond:
                    errors.append(f"Trade {len(trades)} exited on REVERSAL_SHORT but condition was False!")
                if exit_reason == "STRUCTURAL_STOP" and stop_level is None:
                    errors.append(f"Trade {len(trades)} exited on STRUCTURAL_STOP but stop_level was None!")

                current_position = None
                stop_level = None
                
        # 2. Enter New Position
        if current_position is None and in_entry_window:
            if is_long_cond:
                current_position = "LONG"
                entry_price = c
                entry_time = dates[i]
                # Compute structural stop (min of last 5 lows)
                start_idx = max(0, i-5)
                stop_level = np.min(lows[start_idx:i])
            elif is_short_cond:
                current_position = "SHORT"
                entry_price = c
                entry_time = dates[i]
                # Compute structural stop (max of last 5 highs)
                start_idx = max(0, i-5)
                stop_level = np.max(highs[start_idx:i])
                
    return trades, errors

for mode in ["futures"]:
    trades, errors = run_diagnostic_backtest(mode)
    print(f"\n--- {mode.upper()} ---")
    print(f"Total Trades: {len(trades)}")
    print(f"Logic Flaws Found: {len(errors)}")
    
    from collections import Counter
    reasons = Counter([t['reason'] for t in trades])
    print("Exit Reasons Distribution:")
    for k, v in reasons.items():
        print(f"  {k}: {v} ({v/len(trades)*100:.1f}%)")

print("\nE2E logic simulation complete.")
