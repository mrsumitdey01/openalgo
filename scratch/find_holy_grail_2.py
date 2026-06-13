import sys
import os
import pandas as pd
from datetime import datetime
sys.path.append(os.getcwd())

from database.historify_db import get_ohlcv

def get_data(symbol, exchange, start_date_str, end_date_str):
    start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp())
    df = get_ohlcv(symbol, exchange, "1m", start_ts, end_ts)
    if df.empty:
        return None
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["timestamp"], unit='s').dt.tz_localize('UTC').dt.tz_convert('Asia/Kolkata')
    df["time"] = df["datetime"].dt.time
    return df

def simulate_ema_cross(df, fast_len, slow_len, tp_pts, trail_pts, symbol):
    df['ema_fast'] = df['close'].ewm(span=fast_len, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow_len, adjust=False).mean()
    
    qty = 15 if symbol == "BANKNIFTY" else 100
    fee = 100 # Approx round trip fee
    
    closes = df['close'].values
    ema_fast = df['ema_fast'].values
    ema_slow = df['ema_slow'].values
    times = df['time'].values
    
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
                trades.append((excursion * qty) - fee)
                open_pos = None
        
        elif start_time <= t < eod_time:
            if ema_fast[i-1] <= ema_slow[i-1] and ema_fast[i] > ema_slow[i]:
                open_pos = {"type": "LONG", "entry": price, "mfe": 0.0}
            elif ema_fast[i-1] >= ema_slow[i-1] and ema_fast[i] < ema_slow[i]:
                open_pos = {"type": "SHORT", "entry": price, "mfe": 0.0}
                
    net = sum(trades)
    wr = sum(1 for t in trades if t > 0) / len(trades) * 100 if trades else 0
    return net, wr, len(trades)

def main():
    print("Fetching CrudeOil Data...")
    df = get_data("CRUDEOIL", "MCX_INDEX", "2023-10-01", "2024-04-01")
    
    best_net = -999999
    best_params = None
    
    # Grid search
    for fast in [9, 12, 21]:
        for slow in [21, 50, 100]:
            if fast >= slow: continue
            for tp in [50, 100, 150]:
                for trail in [40, 60, 80]:
                    net, wr, cnt = simulate_ema_cross(df, fast, slow, tp, trail, "CRUDEOIL")
                    if net > best_net:
                        best_net = net
                        best_params = (fast, slow, tp, trail)
                    print(f"F:{fast} S:{slow} TP:{tp} Tr:{trail} -> Net: {net:.2f}, WR: {wr:.1f}%, Trades: {cnt}")
                    
    print(f"\nBEST: {best_params} -> Net: {best_net}")

if __name__ == "__main__":
    main()
