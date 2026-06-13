import sys
import os
import json
import pandas as pd
from datetime import datetime
sys.path.append(os.getcwd())

from database.historify_db import get_ohlcv
from strategies.scripts.bot2_mcx_bb_trend import BollingerTrendFilter, check_signals

def simulate_with_params(df, sl_pct, tp_pct, trail_trigger_pct, execution_mode="options_spread"):
    trades = []
    capital = 100000.0
    current_capital = capital
    open_position = None
    
    # Fast array access
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    
    if execution_mode == "options_spread":
        spread_delta = 0.25
        margin_pct = 0.005
        premium_pct = 0.005
    else:
        spread_delta = 1.0
        margin_pct = 0.10
        premium_pct = 1.0
        
    unit_size = 100
    lots = 1
    total_qty = lots * unit_size
    
    for i in range(2, len(df)-1):
        price = closes[i]
        
        # Check signals on previous candle
        slice_df = df.iloc[max(0, i-5):i+1]
        signal = check_signals(slice_df, open_position["type"] if open_position else None)
        
        if open_position is not None:
            spot_diff = price - open_position["entry_spot"]
            if open_position["type"] == "LONG":
                gross_pnl = spot_diff * spread_delta * total_qty
            else:
                gross_pnl = -spot_diff * spread_delta * total_qty
                
            entry_value = open_position["entry_spread"] * total_qty
            pnl_pct = (gross_pnl / entry_value) if entry_value > 0 else 0.0
            
            # Smart Exit Logic
            should_exit = False
            
            if pnl_pct <= -sl_pct:
                should_exit = True
            elif pnl_pct >= tp_pct:
                should_exit = True
            elif signal in ["EXIT_LONG", "EXIT_SHORT"]:
                should_exit = True
                
            if should_exit:
                net_pnl = gross_pnl - 50 # rough fee
                current_capital += net_pnl
                trades.append(net_pnl)
                open_position = None
                
        elif signal in ["LONG", "SHORT"]:
            entry_spread = price * premium_pct
            margin_required = price * margin_pct * total_qty
            
            if current_capital >= margin_required + 50:
                open_position = {
                    "type": signal,
                    "entry_spot": price,
                    "entry_spread": entry_spread,
                }
                
    net_pnl = sum(trades)
    win_rate = sum(1 for t in trades if t > 0) / len(trades) * 100 if trades else 0
    return net_pnl, win_rate, len(trades)

def run():
    start_ts = int(datetime.strptime("2023-10-01", "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime("2024-04-01", "%Y-%m-%d").timestamp())
    
    df = get_ohlcv("CRUDEOIL", "MCX_INDEX", "1m", start_ts, end_ts)
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    bb = BollingerTrendFilter()
    df = bb.compute(df)
    
    best_pnl = -999999
    best_params = None
    
    for sl in [0.05, 0.10, 0.15, 0.25, 0.50, 1.0]:
        for tp in [0.10, 0.20, 0.50, 1.0, 2.0]:
            pnl, wr, n_trades = simulate_with_params(df, sl, tp, 0, "options_spread")
            if pnl > best_pnl:
                best_pnl = pnl
                best_params = (sl, tp)
            print(f"SL: {sl}, TP: {tp} -> PnL: {pnl:.2f}, WR: {wr:.1f}%, Trades: {n_trades}")

run()
