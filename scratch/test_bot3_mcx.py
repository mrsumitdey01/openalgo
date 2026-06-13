import sys
import os
import json
sys.path.append(os.getcwd())

from services.backtest_service import run_bot3_backtest

params = {
    'symbol': 'BANKNIFTY',
    'exchange': 'NSE',
    'start_date': '2024-01-01',
    'end_date': '2024-04-01',
    'capital': 100000.0,
    'execution_mode': 'options_spread',
    'lot_size': 15,
    'apply_brokerage': False
}

success, response, code = run_bot3_backtest(params)

if success:
    metrics = response.get('metrics', {})
    print(f"Metrics (Zero Brokerage): {json.dumps(metrics, indent=2)}")
else:
    print(f"Error: {response}")

# Run with Brokerage
params['apply_brokerage'] = True
success, response, code = run_bot3_backtest(params)
if success:
    metrics = response.get('metrics', {})
    print(f"Metrics (With Brokerage): {json.dumps(metrics, indent=2)}")

