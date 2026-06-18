import sys
import os
import pandas as pd
from collections import defaultdict

sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot4_backtest

def get_year_wise_losses():
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
        "gap_pct_abort": 0.005,       
        "recovery_time": "12:30",
        "rec_divergence_pct": 0.010,  
        "rec_timed_exit": True,
        "rec_timed_exit_hour": 14,
        "use_directional": False
    }

    print("Running 10-Year Backtest to extract trades...")
    success, data, _ = run_bot4_backtest(params)
    
    if not success:
        print("Backtest Failed!")
        return

    trades = data["trades"]
    
    # Aggregate net PnL by day
    daily_pnl = defaultdict(float)
    for t in trades:
        date = t['entry_time'].split(' ')[0]
        daily_pnl[date] += t['net_pnl']
        
    # Aggregate by year
    yearly_stats = defaultdict(lambda: {"loss_days": 0, "total_loss": 0.0, "total_pnl": 0.0})
    
    for date, pnl in daily_pnl.items():
        year = date.split('-')[0]
        yearly_stats[year]["total_pnl"] += pnl
        if pnl < 0:
            yearly_stats[year]["loss_days"] += 1
            yearly_stats[year]["total_loss"] += pnl

    print("\n=======================================================")
    print("YEAR-WISE LOSS DAYS & TOTAL LOSSES (Baseline Bot 4)")
    print("=======================================================")
    print(f"{'Year':<6} | {'Loss Days':<12} | {'Gross Loss on Loss Days (Rs.)':<30} | {'Net Yearly PnL (Rs.)':<20}")
    print("-" * 80)
    
    total_loss_days = 0
    total_gross_loss = 0
    total_net_pnl = 0
    
    for year in sorted(yearly_stats.keys()):
        ld = yearly_stats[year]["loss_days"]
        gl = yearly_stats[year]["total_loss"]
        npnl = yearly_stats[year]["total_pnl"]
        
        total_loss_days += ld
        total_gross_loss += gl
        total_net_pnl += npnl
        
        print(f"{year:<6} | {ld:<12} | {gl:<30.2f} | {npnl:<20.2f}")
        
    print("-" * 80)
    print(f"{'TOTAL':<6} | {total_loss_days:<12} | {total_gross_loss:<30.2f} | {total_net_pnl:<20.2f}")

if __name__ == '__main__':
    get_year_wise_losses()
