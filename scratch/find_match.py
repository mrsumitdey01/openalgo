import sys
import json
sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot4_backtest

def search_params():
    for cap in [185000, 100000]:
        for brk in [True, False]:
            params = {
                "strategy": "bot4_straddle_seller",
                "symbol": "NIFTY",
                "start_date": "2022-01-01",
                "end_date": "2025-01-01",
                "capital": cap,
                "lot_size": 65,
                "entry_time": "09:30",
                "exit_time": "15:15",
                "sl_pct": 0.01,         
                "max_loss_pct": 0.02,   
                "target_type": "fixed_1600",
                "trend_filter_pct": 0.010,
                "rec_timed_exit": True,
                "rec_timed_exit_hour": 14,
                "apply_brokerage": brk
            }
            success, data, code = run_bot4_backtest(params)
            metrics = data["metrics"]
            print(f"Cap: {cap}, Brokerage: {brk} => PnL: {metrics['net_pnl']:.2f}, Win Rate: {metrics['win_rate_pct']:.2f}% ({metrics['winning_trades']}/{metrics['total_trades']})")

if __name__ == "__main__":
    search_params()
