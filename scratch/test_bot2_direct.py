import sys
import os
import json
sys.path.append(os.getcwd())

from services.backtest_mcx_service import run_bot2_mcx_backtest

params = {
    'symbol': 'CRUDEOIL',
    'exchange': 'MCX',
    'start_date': '2023-10-01',
    'end_date': '2024-04-01',
    'capital': 100000.0,
    'execution_mode': 'futures',
    'lot_size': 1
}

try:
    success, result, code = run_bot2_mcx_backtest(params)
    if success:
        metrics = result['metrics']
        print("Metrics:")
        print(json.dumps(metrics, indent=2))
    else:
        print("Failed:", result)
except Exception as e:
    import traceback
    traceback.print_exc()
