import sys
import json
import pandas as pd
from datetime import datetime
sys.path.append('.')
from database.historify_db import get_ohlcv
from services.backtest_service import run_bot1_backtest
from services.backtest_mcx_service import run_bot1_mcx_backtest

PROFILES = ["options_spread", "options_buying", "options_selling", "futures"]
YEAR = "2025"
CAPITAL = 20000000.0
LOT_SIZE = 1

def analyze_trades(trades, df, profile_name, symbol):
    anomalies = []
    for t in trades:
        if t["qty"] != LOT_SIZE:
            anomalies.append(f"Trade {t['id']}: Qty {t['qty']} != {LOT_SIZE}")
        
        try:
            entry_time = datetime.strptime(t["entry_time"], "%Y-%m-%d %H:%M:%S").time()
            exit_time = datetime.strptime(t["exit_time"], "%Y-%m-%d %H:%M:%S").time()
        except:
            continue

        if symbol == "BANKNIFTY":
            from datetime import time
            if not (time(9, 30) <= entry_time <= time(14, 45)):
                anomalies.append(f"Trade {t['id']}: Entry out of bounds {entry_time}")
            if exit_time > time(15, 15):
                anomalies.append(f"Trade {t['id']}: Exit after square off {exit_time}")
        elif symbol == "CRUDEOIL" or symbol == "GOLDM":
            from datetime import time
            if not (time(10, 0) <= entry_time <= time(22, 0)):
                anomalies.append(f"Trade {t['id']}: Entry out of bounds {entry_time}")
            if exit_time > time(22, 30):
                anomalies.append(f"Trade {t['id']}: Exit after square off {exit_time}")

    return len(anomalies)

def print_row(symbol, profile, trades, net_pnl, roi, anomalies):
    print(f"{symbol:<12} | {profile:<16} | Trades: {trades:<5} | Net PnL: {net_pnl:>12.2f} | ROI: {roi:>6.2f}% | Time/Qty Anomalies: {anomalies}")

def main():
    print(f"--- 1-Year Backtest Summary ({YEAR}) | Capital: {CAPITAL} | Lot Size: {LOT_SIZE} ---")
    print("-" * 110)
    
    for profile in PROFILES:
        params = {
            "symbol": "BANKNIFTY",
            "exchange": "NSE_INDEX",
            "start_date": f"{YEAR}-01-01",
            "end_date": f"{YEAR}-12-31",
            "capital": CAPITAL,
            "execution_mode": profile,
            "lot_size": LOT_SIZE
        }
        success, response, code = run_bot1_backtest(params)
        if success:
            df = get_ohlcv("BANKNIFTY", "NSE_INDEX", "1m", 
                           int(datetime.strptime(f"{YEAR}-01-01", "%Y-%m-%d").timestamp()), 
                           int(datetime.strptime(f"{YEAR}-12-31 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()))
            anomalies = analyze_trades(response["trades"], df, profile, "BANKNIFTY")
            metrics = response["metrics"]
            print_row("BANKNIFTY", profile, metrics["total_trades"], metrics["net_pnl"], metrics["roi_pct"], anomalies)
        else:
            print(f"BANKNIFTY {profile} FAILED: {response}")

    print("-" * 110)

    for profile in PROFILES:
        params = {
            "symbol": "CRUDEOIL",
            "exchange": "MCX_INDEX",
            "start_date": f"{YEAR}-01-01",
            "end_date": f"{YEAR}-12-31",
            "capital": CAPITAL,
            "execution_mode": profile,
            "lot_size": LOT_SIZE
        }
        success, response, code = run_bot1_mcx_backtest(params)
        if success:
            df = get_ohlcv("CRUDEOIL", "MCX_INDEX", "1m", 
                           int(datetime.strptime(f"{YEAR}-01-01", "%Y-%m-%d").timestamp()), 
                           int(datetime.strptime(f"{YEAR}-12-31 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()))
            anomalies = analyze_trades(response["trades"], df, profile, "CRUDEOIL")
            metrics = response["metrics"]
            print_row("CRUDEOIL", profile, metrics["total_trades"], metrics["net_pnl"], metrics["roi_pct"], anomalies)
        else:
            print(f"CRUDEOIL {profile} FAILED: {response}")
            
    print("-" * 110)

if __name__ == "__main__":
    main()
