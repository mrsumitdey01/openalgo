import time
from services.backtest_service import run_bot1_backtest

symbol = 'BANKNIFTY'
exchange = 'NSE_INDEX'
start_date = '2021-06-01'
end_date = '2026-06-06'
modes = ['futures', 'options_buying', 'options_selling', 'options_spread']

for mode in modes:
    params = {
        'bot_id': 'bot1',
        'symbol': symbol,
        'exchange': exchange,
        'start_date': start_date,
        'end_date': end_date,
        'capital': 300000,
        'lot_size': 30,
        'execution_mode': mode
    }
    print(f'\n--- Running {mode} ---')
    t0 = time.time()
    try:
        success, response, status = run_bot1_backtest(params)
        t1 = time.time()
        print(f'Time taken: {t1-t0:.2f} seconds')
        if success:
            metrics = response.get('metrics', {})
            trades = len(response.get('trades', []))
            print(f'SUCCESS! Trades: {trades}, Net PnL: {metrics.get("net_pnl")}, Final Capital: {metrics.get("final_capital")}')
        else:
            print(f'FAILED! Response: {response}')
    except Exception as e:
        import traceback
        traceback.print_exc()
