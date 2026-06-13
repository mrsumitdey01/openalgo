import sys
import os
import pandas as pd
from datetime import datetime
sys.path.append(os.getcwd())

from database.historify_db import get_ohlcv
def simulate_ema_cross(df, fast_len, slow_len, tp_pts, trail_pts, symbol):
    df['ema_fast'] = df['close'].ewm(span=fast_len, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_len, adjust=False).mean()
    
    qty = 15 if symbol == "BANKNIFTY" else 100
    fee = 100 # Approx round trip fee
    
    closes = df['close'].values
    ema_fast = df['ema_fast'].values
    ema_slow = df['ema_slow'].values
    times = df['time'].values
    datetimes = df['datetime'].values
    
    trades = []
    open_pos = None
    
    eod_time = datetime.strptime("15:15", "%H:%M").time() if symbol == "BANKNIFTY" else datetime.strptime("23:15", "%H:%M").time()
    start_time = datetime.strptime("09:30", "%H:%M").time() if symbol == "BANKNIFTY" else datetime.strptime("09:00", "%H:%M").time()
    
    for i in range(1, len(df)):
        price = closes[i]
        t = times[i]
        
        if open_pos is not None:
            excursion = price - open_pos["entry"] if open_pos["type"] == "LONG" else open_pos["entry"] - price
            
            if excursion > open_pos["mfe"]:
                open_pos["mfe"] = excursion
                
            mfe = open_pos["mfe"]
            
            should_exit = False
            if mfe >= trail_pts and excursion <= mfe - (trail_pts * 0.5):
                should_exit = True
            elif excursion <= -trail_pts: # SL equals trail activation
                should_exit = True
            elif excursion >= tp_pts:
                should_exit = True
            elif t >= eod_time:
                should_exit = True
                
            if should_exit:
                trades.append({"entry_time": open_pos["dt"], "exit_time": str(datetimes[i]), "type": open_pos["type"], "entry": open_pos["entry"], "exit": price})
                open_pos = None
        
        elif start_time <= t < eod_time:
            if ema_fast[i-1] <= ema_slow[i-1] and ema_fast[i] > ema_slow[i]:
                open_pos = {"type": "LONG", "entry": price, "mfe": 0.0, "dt": str(datetimes[i])}
            elif ema_fast[i-1] >= ema_slow[i-1] and ema_fast[i] < ema_slow[i]:
                open_pos = {"type": "SHORT", "entry": price, "mfe": 0.0, "dt": str(datetimes[i])}
                
    return trades

df = get_ohlcv("BANKNIFTY", "NSE_INDEX", "1m", int(datetime.strptime("2023-10-01", "%Y-%m-%d").timestamp()), int(datetime.strptime("2024-04-01", "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp()))
df = df.sort_values("timestamp").reset_index(drop=True)
df["datetime"] = pd.to_datetime(df["timestamp"], unit='s')
df["time"] = df["datetime"].dt.time
hg_trades = simulate_ema_cross(df, 9, 50, 300, 100, "BANKNIFTY")

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
be_trades = result['trades']

print("HG Trades:")
for t in hg_trades[:5]: print(t)
print("\nBackend Trades:")
for t in be_trades[:5]: print({"entry_time": t["entry_time"], "exit_time": t["exit_time"], "type": t["direction"], "entry": t["entry_price"], "exit": t["exit_price"]})
