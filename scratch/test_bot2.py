import requests

def test_bot2_mcx():
    url = 'http://127.0.0.1:5000/api/backtest/bot2_mcx'
    payload = {
        'symbol': 'CRUDEOIL',
        'exchange': 'MCX',
        'start_date': '2023-10-01',
        'end_date': '2024-04-01',
        'capital': 100000.0,
        'execution_mode': 'options_spread',
        'lot_size': 1
    }
    try:
        response = requests.post(url, json=payload)
        data = response.json()
        if data['status'] == 'success':
            metrics = data['metrics']
            print(f"Bot 2 MCX BB Trend Backtest Results:")
            print(f"Total Trades: {metrics['total_trades']}")
            print(f"Win Rate: {metrics['win_rate_pct']}%")
            print(f"Net PnL: {metrics['net_pnl']}")
            print(f"Max DD: {metrics['max_drawdown_pct']}%")
            print(f"Avg Trade PnL: {metrics['avg_trade_pnl']}")
        else:
            print("Failed:", data.get("message"))
    except Exception as e:
        print("Error:", e)

test_bot2_mcx()
