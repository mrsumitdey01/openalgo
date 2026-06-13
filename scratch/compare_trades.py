import sys
import os
sys.path.append(os.getcwd())

from scratch.find_holy_grail_2 import simulate_ema_cross, get_data

df = get_data("BANKNIFTY", "NSE_INDEX", "2023-10-01", "2024-04-01")
net, wr, cnt = simulate_ema_cross(df, 9, 50, 300, 100, "BANKNIFTY")
print(f"Holy Grail Script: Net={net}, WR={wr}, Trades={cnt}")

from services.backtest_service import run_bot2_backtest

params = {
    'symbol': 'BANKNIFTY',
    'exchange': 'NSE',
    'start_date': '2023-10-01',
    'end_date': '2024-04-01',
    'capital': 100000.0,
    'execution_mode': 'futures',
    'lot_size': 1
}

success, result, code = run_bot2_backtest(params)
if success:
    m = result['metrics']
    print(f"Backend Service: Net={m['net_pnl']}, WR={m['win_rate_pct']}, Trades={m['total_trades']}")
else:
    print("Backend Service Failed:", result)
