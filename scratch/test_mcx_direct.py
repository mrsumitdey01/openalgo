import sys
import os
import json

# Add project root to path
sys.path.append(os.path.abspath('.'))

from services.backtest_mcx_service import run_bot1_mcx_backtest

def run_test():
    params = {
        "bot_id": "bot1_mcx",
        "symbol": "CRUDEOIL",
        "exchange": "MCX",
        "interval": "1",
        "timeframe": "120",
        "profile": "options_spread",
        "capital": 20000000,
        "lot_size": 1
    }
    
    print("Running MCX backtest directly...")
    success, response, status_code = run_bot1_mcx_backtest(params)
    
    print(f"Success: {success}, Status Code: {status_code}")
    print("Metrics:", response.get("metrics"))
    
    trades = response.get("trades", [])
    print(f"Total trades: {len(trades)}")
    
    mcx_trades = 0
    invalid_trades = 0
    for trade in trades:
        try:
            # trade['entry_time'] format: "2026-04-01 10:15:00"
            time_str = trade.get("entry_time", "").split(" ")[1]
            h, m, s = map(int, time_str.split(":"))
            
            # Check if trade happened strictly after 15:30 (NSE close) or before 09:30
            if h >= 16:
                mcx_trades += 1
            elif h < 9 or (h == 9 and m < 30):
                invalid_trades += 1
        except Exception as e:
            pass
            
    print(f"Trades strictly after 16:00 (MCX evidence): {mcx_trades}")
    print(f"Invalid trades (before 09:30): {invalid_trades}")
    
    # Check max time
    if trades:
        last_trade_time = max([t.get("exit_time", "") for t in trades])
        print(f"Latest exit time: {last_trade_time}")

if __name__ == "__main__":
    run_test()
