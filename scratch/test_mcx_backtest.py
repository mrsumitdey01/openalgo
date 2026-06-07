import requests

def test_mcx_backtest():
    url = "http://127.0.0.1:5000/api/backtest_bot"
    payload = {
        "bot_id": "bot1_mcx",
        "symbol": "CRUDEOIL",
        "exchange": "MCX",
        "interval": "1",
        "timeframe": "120",
        "profile": "options_spread",
        "capital": 20000000,
        "lot_size": 1
    }
    
    print(f"Triggering backtest for bot1_mcx with payload: {payload}")
    try:
        res = requests.post(url, json=payload, timeout=60)
        print(f"Status: {res.status_code}")
        data = res.json()
        print("Metrics:", data.get("metrics"))
        trades = data.get("trades", [])
        print(f"Total trades: {len(trades)}")
        
        # Verify timestamps of trades
        mcx_trades = 0
        non_mcx_trades = 0
        for trade in trades:
            time_str = trade.get("entry_time", "").split(" ")[1]
            h, m, s = map(int, time_str.split(":"))
            # Normal NSE times are 09:30 to 15:30. MCX is 10:00 to 22:30.
            # So if we see trades at 21:00 or 10:00, it's MCX logic.
            if h >= 16:
                mcx_trades += 1
            elif h < 9 or (h == 9 and m < 30):
                non_mcx_trades += 1 # Invalid
                
        print(f"Trades strictly after 16:00 (MCX evidence): {mcx_trades}")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_mcx_backtest()
