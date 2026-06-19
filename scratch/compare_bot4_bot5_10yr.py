import sys
import os
import json
import pandas as pd
from datetime import datetime

sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot4_backtest, run_bot5_backtest

def build_periodic_report(trades):
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['year'] = df['entry_time'].dt.year
    df['month'] = df['entry_time'].dt.month
    
    yearly = df.groupby('year')['net_pnl'].sum().to_dict()
    monthly = df.groupby(['year', 'month'])['net_pnl'].sum().to_dict()
    
    return {
        "yearly": {int(k): round(v, 2) for k, v in yearly.items()},
        "monthly": {f"{k[0]}-{k[1]:02d}": round(v, 2) for k, v in monthly.items()}
    }

def run_comparison():
    params_bot4 = {
        "strategy": "bot4_straddle_seller",
        "symbol": "NIFTY",
        "start_date": "2016-01-01",
        "end_date": "2026-12-31",
        "capital": 185000,
        "qty": 25,
        "entry_time": "09:30",
        "exit_time": "15:15",
        "sl_pct": 0.01,
        "max_loss_pct": 0.02,
        "target_type": "dynamic_day_based",
        "gap_pct_abort": 0.005,
        "recovery_time": "12:30",
        "rec_divergence_pct": 0.010,
        "rec_timed_exit": True,
        "rec_timed_exit_hour": 14,
        "use_directional": False
    }

    params_bot5 = {
        "strategy": "bot5_straddle_seller",
        "symbol": "NIFTY",
        "start_date": "2016-01-01",
        "end_date": "2026-12-31",
        "capital": 185000,
        "qty": 25,
        "entry_time": "10:00",
        "exit_time": "15:15",
        "sl_pct": 0.01,
        "max_loss_pct": 0.02,
        "target_type": "dynamic_day_based",
        "gap_pct_abort": 0.008,
        "recovery_time": "12:30",
        "rec_divergence_pct": 0.010,
        "rec_timed_exit": True,
        "rec_timed_exit_hour": 14,
        "use_directional": False
    }

    print("======================================================")
    print("RUNNING 10-YEAR BACKTEST: BOT 4 (09:30 Entry)...")
    print("======================================================")
    success_4, b4_data, _ = run_bot4_backtest(params_bot4)
    
    print("\n======================================================")
    print("RUNNING 10-YEAR BACKTEST: BOT 5 (10:00 Entry)...")
    print("======================================================")
    success_5, b5_data, _ = run_bot5_backtest(params_bot5)
    
    if not success_4 or not success_5:
        print("Backtest simulation failed!")
        return
        
    b4_met = b4_data["metrics"]
    b5_met = b5_data["metrics"]
    
    b4_trades = b4_data.get("trades", [])
    b5_trades = b5_data.get("trades", [])
    
    b4_periodic = build_periodic_report(b4_trades)
    b5_periodic = build_periodic_report(b5_trades)
    
    report = {
        "bot4_metrics": b4_met,
        "bot5_metrics": b5_met,
        "bot4_periodic": b4_periodic,
        "bot5_periodic": b5_periodic
    }
    
    with open("10yr_comparison_report.json", "w") as f:
        json.dump(report, f, indent=4)
        
    print("\n\n========================================")
    print("10-YEAR BOT4 VS BOT5 COMPARISON RESULTS")
    print("========================================")
    
    print(f"{'Metric':<25} | {'Bot 4 (09:30)':<15} | {'Bot 5 (10:00)':<15}")
    print("-" * 60)
    print(f"{'Net PnL (Rs.)':<25} | {b4_met['net_pnl']:<15.2f} | {b5_met['net_pnl']:<15.2f}")
    print(f"{'Win Rate (%)':<25} | {b4_met['win_rate_pct']:<15.2f} | {b5_met['win_rate_pct']:<15.2f}")
    print(f"{'Max Drawdown (%)':<25} | {b4_met['max_drawdown_pct']:<15.2f} | {b5_met['max_drawdown_pct']:<15.2f}")
    print(f"{'Total Trades':<25} | {b4_met['total_trades']:<15} | {b5_met['total_trades']:<15}")
    print(f"{'Winning Trades':<25} | {b4_met['winning_trades']:<15} | {b5_met['winning_trades']:<15}")
    print(f"{'Losing Trades':<25} | {b4_met['losing_trades']:<15} | {b5_met['losing_trades']:<15}")
    
    diff_pnl = b5_met['net_pnl'] - b4_met['net_pnl']
    print("-" * 60)
    print(f"BOT 5 PNL DIFFERENCE vs BOT 4: Rs. {diff_pnl:.2f}")

if __name__ == '__main__':
    run_comparison()
