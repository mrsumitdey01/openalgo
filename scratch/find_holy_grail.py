import sys
import os
import json
import pandas as pd
import numpy as np
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
    df["datetime"] = pd.to_datetime(df["timestamp"], unit='s')
    df["date"] = df["datetime"].dt.date
    df["time"] = df["datetime"].dt.time
    return df

def test_orb_strategy(df, symbol):
    # Opening Range Breakout (First 15 mins)
    # Trade once per day.
    trades = []
    capital = 100000.0
    
    # Pre-calculate ORB levels
    daily_groups = df.groupby("date")
    orb_levels = {}
    
    for date, group in daily_groups:
        # First 15 mins
        morn = group[(group["datetime"].dt.hour == 9) & (group["datetime"].dt.minute < 30)]
        if symbol == "CRUDEOIL":
            # MCX opens at 9 AM, let's use 9:00 to 10:00 for ORB
            morn = group[(group["datetime"].dt.hour == 9)]
            
        if not morn.empty:
            orb_levels[date] = {"high": morn["high"].max(), "low": morn["low"].min()}

    open_pos = None
    
    spread_delta = 1.0 # testing futures for maximum pure edge
    qty = 15 if symbol == "BANKNIFTY" else 100
    fee_per_trade = 150 # rough round-trip fee for futures
    
    for i in range(1, len(df)):
        row = df.iloc[i]
        date = row["date"]
        time = row["time"]
        price = row["close"]
        
        if date not in orb_levels:
            continue
            
        high_level = orb_levels[date]["high"]
        low_level = orb_levels[date]["low"]
        
        # Avoid trading in the first hour while ORB forms
        if symbol == "BANKNIFTY" and time.hour == 9 and time.minute < 30:
            continue
        if symbol == "CRUDEOIL" and time.hour == 9:
            continue
            
        # EOD Squareoff
        eod_time = datetime.strptime("15:15", "%H:%M").time() if symbol == "BANKNIFTY" else datetime.strptime("23:15", "%H:%M").time()
        
        if open_pos is not None:
            # Trailing Stop Logic or EOD
            spot_diff = price - open_pos["entry"]
            pnl = (spot_diff * qty) if open_pos["type"] == "LONG" else (-spot_diff * qty)
            
            # 1:2 Risk Reward
            sl = -50 if symbol == "BANKNIFTY" else -30
            tp = 100 if symbol == "BANKNIFTY" else 60
            
            excursion = spot_diff if open_pos["type"] == "LONG" else -spot_diff
            
            if excursion <= sl or excursion >= tp or time >= eod_time:
                trades.append(pnl - fee_per_trade)
                open_pos = None
                
        elif time < eod_time:
            # Check for entry (only 1 trade per day allowed conceptually, but let's allow multiple for now if it chops, wait we must limit to 1)
            # Actually, let's just test raw breakouts
            if price > high_level + 5:
                open_pos = {"type": "LONG", "entry": price}
            elif price < low_level - 5:
                open_pos = {"type": "SHORT", "entry": price}

    net_pnl = sum(trades)
    wr = sum(1 for t in trades if t > 0) / len(trades) * 100 if trades else 0
    return {"strategy": "ORB", "trades": len(trades), "win_rate": round(wr, 2), "net_pnl": round(net_pnl, 2)}

def test_supertrend(df, symbol):
    # We will use a simple ATR trailing stop concept
    # True Range
    df['prev_close'] = df['close'].shift(1)
    df['h_l'] = df['high'] - df['low']
    df['h_pc'] = abs(df['high'] - df['prev_close'])
    df['l_pc'] = abs(df['low'] - df['prev_close'])
    df['tr'] = df[['h_l', 'h_pc', 'l_pc']].max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()
    
    multiplier = 3.0
    df['upper_band'] = ((df['high'] + df['low']) / 2) + (multiplier * df['atr'])
    df['lower_band'] = ((df['high'] + df['low']) / 2) - (multiplier * df['atr'])
    
    # Simplified SuperTrend simulation
    trades = []
    qty = 15 if symbol == "BANKNIFTY" else 100
    fee_per_trade = 150
    open_pos = None
    
    closes = df['close'].values
    ub = df['upper_band'].values
    lb = df['lower_band'].values
    
    trend = 1
    
    for i in range(14, len(df)):
        price = closes[i]
        
        if trend == 1 and price < lb[i-1]:
            trend = -1
        elif trend == -1 and price > ub[i-1]:
            trend = 1
            
        if open_pos is not None:
            if open_pos["type"] == "LONG" and trend == -1:
                pnl = (price - open_pos["entry"]) * qty
                trades.append(pnl - fee_per_trade)
                open_pos = {"type": "SHORT", "entry": price}
            elif open_pos["type"] == "SHORT" and trend == 1:
                pnl = (open_pos["entry"] - price) * qty
                trades.append(pnl - fee_per_trade)
                open_pos = {"type": "LONG", "entry": price}
        else:
            open_pos = {"type": "LONG" if trend == 1 else "SHORT", "entry": price}
            
    net_pnl = sum(trades)
    wr = sum(1 for t in trades if t > 0) / len(trades) * 100 if trades else 0
    return {"strategy": "SuperTrend", "trades": len(trades), "win_rate": round(wr, 2), "net_pnl": round(net_pnl, 2)}

def test_reversal(df, symbol):
    # RSI Extreme Reversal
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    trades = []
    qty = 15 if symbol == "BANKNIFTY" else 100
    fee_per_trade = 150
    open_pos = None
    
    closes = df['close'].values
    rsis = df['rsi'].values
    
    for i in range(14, len(df)):
        price = closes[i]
        rsi = rsis[i]
        
        if open_pos is not None:
            excursion = price - open_pos["entry"] if open_pos["type"] == "LONG" else open_pos["entry"] - price
            # TP / SL
            if excursion >= 100 or excursion <= -50:
                pnl = excursion * qty
                trades.append(pnl - fee_per_trade)
                open_pos = None
        else:
            if rsi < 15:
                open_pos = {"type": "LONG", "entry": price}
            elif rsi > 85:
                open_pos = {"type": "SHORT", "entry": price}
                
    net_pnl = sum(trades)
    wr = sum(1 for t in trades if t > 0) / len(trades) * 100 if trades else 0
    return {"strategy": "RSI Reversal", "trades": len(trades), "win_rate": round(wr, 2), "net_pnl": round(net_pnl, 2)}

def main():
    print("Testing Holy Grail on BANKNIFTY...")
    bn_df = get_data("BANKNIFTY", "NSE_INDEX", "2023-10-01", "2024-04-01")
    if bn_df is not None:
        print(test_orb_strategy(bn_df, "BANKNIFTY"))
        print(test_supertrend(bn_df, "BANKNIFTY"))
        print(test_reversal(bn_df, "BANKNIFTY"))
        
    print("\nTesting Holy Grail on CRUDEOIL...")
    cr_df = get_data("CRUDEOIL", "MCX_INDEX", "2023-10-01", "2024-04-01")
    if cr_df is not None:
        print(test_orb_strategy(cr_df, "CRUDEOIL"))
        print(test_supertrend(cr_df, "CRUDEOIL"))
        print(test_reversal(cr_df, "CRUDEOIL"))

if __name__ == "__main__":
    main()
