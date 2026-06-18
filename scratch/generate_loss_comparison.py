import pandas as pd
import json
import sys
import os

# Add the parent directory to the path so we can import services
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import services.backtest_service as bs

def get_daily_pnl(trades):
    daily = {}
    for t in trades:
        date = t['entry_time'].split(' ')[0]
        daily[date] = daily.get(date, 0) + t['net_pnl']
    return daily

def run_comparison():
    params = {
        "strategy": "bot4_straddle_seller",
        "symbol": "NIFTY",
        "start_date": "2016-01-01",
        "end_date": "2026-12-31",
        "capital": 185000,
        "qty": 65,
        "entry_time": "09:30",
        "exit_time": "15:15",
        "sl_pct": 0.01,         
        "max_loss_pct": 0.02,   
        "target_type": "dynamic_day_based",
        "gap_pct_abort": 0.010,      
        "recovery_time": "12:30",
        "rec_divergence_pct": 0.010, 
        "rec_timed_exit": True,
        "rec_timed_exit_hour": 14,
    }

    print("Running Baseline (Hedged Straddle Recovery)...")
    params["use_directional"] = False
    success, base_data, _ = bs.run_bot4_backtest(params)
    base_daily = get_daily_pnl(base_data["trades"])
    
    print("Running New Logic (Directional Recovery)...")
    params["use_directional"] = True
    success, new_data, _ = bs.run_bot4_backtest(params)
    new_daily = get_daily_pnl(new_data["trades"])
    
    # Get union of all dates that had a loss in EITHER run
    all_dates = set(base_daily.keys()).union(set(new_daily.keys()))
    loss_dates = [d for d in all_dates if base_daily.get(d, 0) < 0 or new_daily.get(d, 0) < 0]
    loss_dates.sort()
    
    md_content = "# Before vs After: Loss Days Comparison\n\n"
    md_content += "This table shows every day across the 10-year backtest that ended in a net loss in either the original (hedged straddle) recovery or the new (directional) recovery.\n\n"
    md_content += "| Date | Before (Hedged Straddle) PnL | After (Directional) PnL | Difference |\n"
    md_content += "| --- | --- | --- | --- |\n"
    
    total_before = 0
    total_after = 0
    
    for d in loss_dates:
        b_pnl = base_daily.get(d, 0)
        n_pnl = new_daily.get(d, 0)
        diff = n_pnl - b_pnl
        
        md_content += f"| {d} | Rs. {b_pnl:.2f} | Rs. {n_pnl:.2f} | Rs. {diff:.2f} |\n"
        
        if b_pnl < 0: total_before += b_pnl
        if n_pnl < 0: total_after += n_pnl

    md_content += f"\n**Total PnL on these specific loss days:** Before: Rs. {total_before:.2f} | After: Rs. {total_after:.2f}\n"
    
    artifact_path = r"C:\Users\sumit\.gemini\antigravity\brain\9587d968-b1ce-47b3-8d2b-f7825a14166b\loss_days_comparison.md"
    with open(artifact_path, "w") as f:
        f.write(md_content)
        
    print(f"Done! Written to {artifact_path}")

if __name__ == "__main__":
    run_comparison()
