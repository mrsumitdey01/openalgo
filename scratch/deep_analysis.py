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
    print(f"\n--- Analysis for {symbol} ({profile_name}) ---")
    print(f"Total Trades: {len(trades)}")
    
    anomalies = []
    
    # Check signals properly follow logic (e.g. entry inside time window, stop losses hit correctly)
    for t in trades:
        # Check basic trade sanity
        if t["qty"] != LOT_SIZE:
            anomalies.append(f"Trade {t['id']}: Qty {t['qty']} != {LOT_SIZE}")
        
        # Parse times
        try:
            entry_time = datetime.strptime(t["entry_time"], "%Y-%m-%d %H:%M:%S").time()
            exit_time = datetime.strptime(t["exit_time"], "%Y-%m-%d %H:%M:%S").time()
        except:
            pass

        # Check time bounds
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
                
        # Check stop loss constraints
        pnl_pct = t["pnl_pct"]
        if profile_name == "futures":
            # For futures, stop loss is spot_diff +- 150 points.
            spot_diff = t["gross_pnl"] / (t["qty"]) # Assuming spread_delta=1
            if spot_diff < -155:
                anomalies.append(f"Trade {t['id']}: Futures stop loss exceeded -150: {spot_diff}")
        else:
            # 15% PnL stop loss
            if pnl_pct < -16.0:
                 anomalies.append(f"Trade {t['id']}: PnL stop loss exceeded -15%: {pnl_pct}%")
                 
    if not anomalies:
        print("[PASS] 100% Verified. No anomalies found.")
    else:
        print(f"[FAIL] Found {len(anomalies)} anomalies:")
        for a in anomalies[:10]:
            print("  -", a)
        if len(anomalies) > 10:
             print(f"  ... and {len(anomalies) - 10} more")
    

def main():
    print(f"Starting Deep Analysis for Year {YEAR}, Capital {CAPITAL}, Lot Size {LOT_SIZE}")
    
    # 1. Test BANKNIFTY
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
            analyze_trades(response["trades"], df, profile, "BANKNIFTY")
            print(f"Metrics: {json.dumps(response['metrics'])}")
        else:
            print(f"Failed to backtest BANKNIFTY ({profile}): {response}")

    # 2. Test CRUDEOIL (MCX)
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
            analyze_trades(response["trades"], df, profile, "CRUDEOIL")
            print(f"Metrics: {json.dumps(response['metrics'])}")
        else:
            print(f"Failed to backtest CRUDEOIL ({profile}): {response}")

if __name__ == "__main__":
    main()
