import sys
import os
import json

sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot4_backtest

def run_10yr_verification():
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
        "target_type": "fixed_1600",
        "gap_pct_abort": 0.005,      
        "recovery_time": "12:30",
        "rec_divergence_pct": 0.010, 
        
        # PROVEN BEST SETTINGS
        "rec_timed_exit": True,
        "rec_timed_exit_hour": 14,
    }

    print("Running Final Bot 4 10-YEAR Production Regression Sweep...")
    success, data, code = run_bot4_backtest(params)
    
    if not success:
        print("Verification Failed!")
        return
        
    metrics = data["metrics"]
    print("="*50)
    print("FINAL BOT 4 10-YEAR VERIFIED METRICS")
    print("="*50)
    print(f"Total Net PnL: Rs.{metrics['net_pnl']:.2f}")
    print(f"Max Drawdown: {metrics['max_drawdown_pct']:.2f}%")
    print(f"Win Rate: {metrics['win_rate_pct']:.2f}%")
    print(f"Total Trades: {metrics['total_trades']}")
    print(f"Winning Trades: {metrics['winning_trades']}")
    print(f"Losing Trades: {metrics['losing_trades']}")
    print("="*50)
    
    with open("bot4_10yr_verified.json", "w") as f:
        json.dump(data, f, indent=4)
        
if __name__ == "__main__":
    run_10yr_verification()
