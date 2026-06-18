import sys
import os
import json

sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot4_backtest

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
        "gap_pct_abort": 0.005,       # CORRECT VALUE: 0.5%
        "recovery_time": "12:30",
        "rec_divergence_pct": 0.010,  # CORRECT VALUE: 1.0%
        "rec_timed_exit": True,
        "rec_timed_exit_hour": 14,
    }

    print("======================================================")
    print("RUNNING 10-YEAR BASELINE (Hedged Straddle Recovery)...")
    print("======================================================")
    params["use_directional"] = False
    success_b, base_data, _ = run_bot4_backtest(params)
    
    print("\n======================================================")
    print("RUNNING 10-YEAR NEW LOGIC (Directional Momentum Recovery)...")
    print("======================================================")
    params["use_directional"] = True
    success_n, new_data, _ = run_bot4_backtest(params)
    
    if not success_b or not success_n:
        print("Verification Failed!")
        return
        
    print("\n\n========================================")
    print("10-YEAR BACKTEST COMPARISON RESULTS")
    print("========================================")
    
    b_met = base_data["metrics"]
    n_met = new_data["metrics"]
    
    print(f"{'Metric':<25} | {'Old Recovery':<15} | {'New Recovery':<15}")
    print("-" * 60)
    print(f"{'Net PnL (Rs.)':<25} | {b_met['net_pnl']:<15.2f} | {n_met['net_pnl']:<15.2f}")
    print(f"{'Win Rate (%)':<25} | {b_met['win_rate_pct']:<15.2f} | {n_met['win_rate_pct']:<15.2f}")
    print(f"{'Max Drawdown (%)':<25} | {b_met['max_drawdown_pct']:<15.2f} | {n_met['max_drawdown_pct']:<15.2f}")
    print(f"{'Total Trades':<25} | {b_met['total_trades']:<15} | {n_met['total_trades']:<15}")
    print(f"{'Winning Trades':<25} | {b_met['winning_trades']:<15} | {n_met['winning_trades']:<15}")
    print(f"{'Losing Trades':<25} | {b_met['losing_trades']:<15} | {n_met['losing_trades']:<15}")
    
    diff_pnl = n_met['net_pnl'] - b_met['net_pnl']
    print("-" * 60)
    print(f"DIFFERENCE IN PNL: Rs. {diff_pnl:.2f}")

if __name__ == '__main__':
    run_comparison()
