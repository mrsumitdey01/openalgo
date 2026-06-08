import sys
import pandas as pd
from datetime import datetime, timedelta
import logging

sys.path.append('.')
from services.backtest_service import run_bot1_backtest
from services.backtest_mcx_service import run_bot1_mcx_backtest

logging.basicConfig(level=logging.INFO)

# Run a programmatic backtest
def run_and_verify(exchange, symbol, execution_mode, start_date, end_date):
    print(f"\n{'='*80}")
    print(f"ANALYZING: {exchange} | {symbol} | {execution_mode} | {start_date} to {end_date}")
    print(f"{'='*80}")
    
    params = {
        "symbol": symbol,
        "exchange": exchange,
        "start_date": start_date,
        "end_date": end_date,
        "capital": 100000,
        "execution_mode": execution_mode,
        "lot_size": 1 if exchange == "MCX" else 30
    }
    
    if exchange == "MCX":
        success, result, status_code = run_bot1_mcx_backtest(params)
    else:
        success, result, status_code = run_bot1_backtest(params)
        
    if not success or status_code != 200:
        print(f"Failed to run backtest: {result}")
        return
        
    trades = result.get("trades", [])
    print(f"Total Trades Executed: {len(trades)}")
    
    if not trades:
        print("No trades found.")
        return
        
    # Analyze trades
    eod_exits = 0
    pnl_stop_exits = 0
    structural_stop_exits = 0
    signal_exits = 0
    anomalies = []
    
    for t in trades:
        reason = t.get("exit_reason", "")
        if "EOD" in reason: eod_exits += 1
        elif "PnL" in reason: pnl_stop_exits += 1
        elif "Structural" in reason: structural_stop_exits += 1
        elif "Signal" in reason: signal_exits += 1
        
        # Verify net PnL math
        gross = t["gross_pnl"]
        fees = t["entry_fee"] + t["exit_fee"]
        net = t["net_pnl"]
        
        if abs((gross - fees) - net) > 0.05:
            anomalies.append(f"Trade {t['id']}: Math mismatch. Gross {gross} - Fees {fees} != Net {net}")
            
    print(f"\nExit Reasons Breakdown:")
    print(f"  EOD Square-Off : {eod_exits}")
    print(f"  15% PnL Stop   : {pnl_stop_exits}")
    print(f"  Structural Stop: {structural_stop_exits}")
    print(f"  Signal Exit    : {signal_exits}")
    
    if anomalies:
        print("\nANOMALIES DETECTED:")
        for a in anomalies:
            print(f"  - {a}")
    else:
        print("\nAll trades passed internal math verification.")
        
    # Sample 3 random trades to display full trace
    import random
    sample_size = min(3, len(trades))
    samples = random.sample(trades, sample_size)
    print("\nSAMPLE TRADES (Full Trace):")
    for t in samples:
        print(f"  Trade {t['id']}: {t['direction']} | Entry: {t['entry_time']} @ {t['entry_price']} | Exit: {t['exit_time']} @ {t['exit_price']} | Reason: {t['exit_reason']} | Net PnL: {t['net_pnl']}")
    print("-" * 80)

# Run tests on all available history
run_and_verify("NSE_INDEX", "BANKNIFTY", "futures", None, None)
run_and_verify("NSE_INDEX", "BANKNIFTY", "options_spread", None, None)

run_and_verify("MCX_INDEX", "CRUDEOIL", "futures", None, None)
run_and_verify("MCX_INDEX", "CRUDEOIL", "options_buying", None, None)
