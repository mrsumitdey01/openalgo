import sys
sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot4_backtest

def run():
    params = {
        "strategy": "bot4_straddle_seller",
        "symbol": "NIFTY",
        "start_date": "2022-01-01",
        "end_date": "2025-01-01",
        "capital": 100000,
        "qty": 65,
        "entry_time": "09:30",
        "exit_time": "15:15",
        "sl_pct": 0.01,         
        "max_loss_pct": 0.02,   
        "target_type": "pct_capital",
        "trend_filter_pct": 0.010,
        "rec_timed_exit": True,
        "rec_timed_exit_hour": 14,
        "apply_brokerage": False
    }
    _, data, _ = run_bot4_backtest(params)
    print("Pct Capital, No Brokerage:", data["metrics"]["net_pnl"])
    
    params["apply_brokerage"] = True
    _, data, _ = run_bot4_backtest(params)
    print("Pct Capital, Brokerage:", data["metrics"]["net_pnl"])

if __name__ == "__main__":
    run()
