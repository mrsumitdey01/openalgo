import sys
import os
from datetime import datetime
import pandas as pd

# Add the openalgo root to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.backtest_service import run_bot4_backtest

years = [2021, 2022, 2023, 2024, 2025, 2026]
symbols = [
    {"sym": "NIFTY", "exch": "NSE", "cap": 800000},
    {"sym": "BANKNIFTY", "exch": "NSE", "cap": 800000},
    {"sym": "SENSEX", "exch": "BSE", "cap": 800000}
]

print("=== 5-YEAR BOT 4 (DYNAMIC ROLL) FORENSIC BACKTEST ===")

all_trades = []
results_summary = []

for s in symbols:
    print(f"\n--- Running for {s['sym']} ---")
    for year in years:
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        
        params = {
            "symbol": s['sym'],
            "exchange": s['exch'],
            "capital": s['cap'],
            "start_date": start_date,
            "end_date": end_date,
            "execution_mode": "options_selling",
            "apply_brokerage": True
        }
        
        success, res, code = run_bot4_backtest(params)
        if success:
            metrics = res["metrics"]
            trades = res["trades"]
            print(f"[{year}] ROI: {metrics['roi_pct']:.2f}% | WinRate: {metrics['win_rate_pct']:.2f}% | PnL: Rs.{metrics['net_pnl']:.2f} | DD: {metrics['max_drawdown_pct']:.2f}% | Trades: {metrics['total_trades']}")
            results_summary.append({
                "Symbol": s['sym'],
                "Year": year,
                "ROI_pct": metrics['roi_pct'],
                "WinRate": metrics['win_rate_pct'],
                "NetPnL": metrics['net_pnl'],
                "MaxDD": metrics['max_drawdown_pct']
            })
            for t in trades:
                t['symbol'] = s['sym']
                t['year'] = year
            all_trades.extend(trades)
        else:
            print(f"[{year}] ERROR: {res['message']}")

df = pd.DataFrame(all_trades)
# Dump top 50 losing trades
if not df.empty:
    worst_trades = df.sort_values("net_pnl").head(50)
    worst_trades.to_csv("scratch/worst_50_losses.csv", index=False)
    print("\nSaved 50 worst losing trades to scratch/worst_50_losses.csv")
    
    # Analyze by exit reason
    print("\nLosses grouped by Exit Reason:")
    losing = df[df['net_pnl'] < 0]
    print(losing.groupby('exit_reason')['net_pnl'].agg(['count', 'sum', 'mean']))

pd.DataFrame(results_summary).to_csv("scratch/year_wise_summary.csv", index=False)
print("Saved summary to scratch/year_wise_summary.csv")
