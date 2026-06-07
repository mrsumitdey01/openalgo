import sys
import os
import json

sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot1_backtest

params = {
    'symbol': 'BANKNIFTY',
    'exchange': 'NSE_INDEX',
    'execution_mode': 'options_spread',
    'capital': 300000.0,
    'lot_size': 30,
    'start_date': '2019-01-01',
    'end_date': '2026-06-06'
}

success, response, code = run_bot1_backtest(params)
trades = response['trades']
print(f"Total trades: {len(trades)}")
if trades:
    print(f"Last trade: {trades[-1]['exit_time']}")
print(f"Final capital: {response.get('metrics', {}).get('final_capital')}")
