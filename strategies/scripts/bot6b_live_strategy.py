#!/usr/bin/env python
import os
import sys
import time
from datetime import datetime, timedelta
import pandas as pd

# Add the root openalgo directory to sys.path so we can import bot6b
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from bot6b.config import (
    MARKET_START, CUTOFF_TIME, SQUARE_OFF_TIME
)
from bot6b.dtc_indicator import compute_dtc, get_actionable_signals
from bot6b.position_manager import Position, Side, compute_quantity

from openalgo import api

# Parameters
SYMBOL = os.getenv('SYMBOL', 'RELIANCE')
EXCHANGE = os.getenv('OPENALGO_STRATEGY_EXCHANGE', os.getenv('EXCHANGE', 'NSE'))
API_KEY = os.getenv('OPENALGO_API_KEY', '')
HOST = os.getenv('HOST_SERVER') or os.getenv('OPENALGO_HOST', 'http://127.0.0.1:5000')
WS_URL = os.getenv('WEBSOCKET_URL') or f"ws://{os.getenv('WEBSOCKET_HOST', '127.0.0.1')}:{os.getenv('WEBSOCKET_PORT', '8765')}"

if not API_KEY:
    print("Warning: OPENALGO_API_KEY is missing. Running in dry/debug mode if not fully integrated.")

client = api(api_key=API_KEY, host=HOST, ws_url=WS_URL)

def _time_str(ts: datetime) -> str:
    return ts.strftime("%H:%M")

def _is_before(ts: datetime, fence: str) -> bool:
    return _time_str(ts) < fence

def _is_after(ts: datetime, fence: str) -> bool:
    return _time_str(ts) >= fence

def main():
    print(f"Bot 6 Live Strategy started at {datetime.now()}")
    print(f"Trading {SYMBOL} on {EXCHANGE}")
    
    position = None
    
    while True:
        try:
            now = datetime.now()
            
            # 1. HARD SQUARE-OFF
            if _is_after(now, SQUARE_OFF_TIME):
                if position and position.is_open:
                    print(f"[{now}] Hard square-off time reached. Exiting position.")
                    response = client.placesmartorder(
                        strategy="Bot6bbb_DTC", symbol=SYMBOL, action="SELL" if position.side == Side.LONG else "BUY",
                        exchange=EXCHANGE, price_type="MARKET", product="MIS",
                        quantity=position.qty, position_size=position.qty * (-1 if position.side == Side.LONG else 1)
                    )
                    position.close()
                    print(f"Square-off Response: {response}")
                else:
                    print(f"[{now}] Outside market hours or past square-off. Sleeping for 60s...")
                time.sleep(60)
                continue

            # Fetch last 5 days to get enough data for 40 EMA
            end_date = now.strftime("%Y-%m-%d")
            start_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")
            
            df = client.history(
                symbol=SYMBOL, exchange=EXCHANGE, interval="1m",
                start_date=start_date, end_date=end_date
            )
            
            if df.empty or 'close' not in df.columns:
                print(f"[{now}] No historical data found or missing 'close'. Retrying in 10s...")
                time.sleep(10)
                continue
            
            # Compute DTC Indicator
            df_dtc = compute_dtc(df)
            signals = get_actionable_signals(df_dtc)
            
            latest_bar = df.iloc[-1]
            latest_open = latest_bar['open']
            latest_high = latest_bar['high']
            latest_low = latest_bar['low']
            latest_close = latest_bar['close']
            
            latest_action_buy = signals['action_buy'].iloc[-1]
            latest_action_sell = signals['action_sell'].iloc[-1]

            # 2. UPDATE TRAILING STOP (before checking exits)
            if position and position.is_open:
                position.update_trail(latest_high, latest_low)

            # 3. CHECK EXIT CONDITIONS
            if position and position.is_open:
                exit_result = position.check_exit(latest_high, latest_low, latest_close)
                if exit_result:
                    exit_px, reason = exit_result
                    print(f"[{now}] Exiting position due to: {reason.value} at approx {exit_px}")
                    response = client.placesmartorder(
                        strategy="Bot6bbb_DTC", symbol=SYMBOL, action="SELL" if position.side == Side.LONG else "BUY",
                        exchange=EXCHANGE, price_type="MARKET", product="MIS",
                        quantity=position.qty, position_size=position.qty * (-1 if position.side == Side.LONG else 1)
                    )
                    position.close()
                    position = None
                    print(f"Exit Order Response: {response}")
                    time.sleep(10)
                    continue

            # 4. CHECK ENTRY CONDITIONS
            if _is_before(now, MARKET_START):
                print(f"[{now}] Pre-market. Waiting for {MARKET_START}...")
                time.sleep(30)
                continue
            
            if _is_after(now, CUTOFF_TIME):
                print(f"[{now}] Past entry cutoff ({CUTOFF_TIME}). Waiting for square-off...")
                time.sleep(30)
                continue
                
            if position and position.is_open:
                # Log state while in trade
                print(f"[{now}] IN TRADE | SL: {position.trail_sl:.2f} | Target: {position.target:.2f} | LTP: {latest_close:.2f}")
                time.sleep(5) # Poll every 5s while in position to track trail SL tighter
                continue

            # Check signals for entry
            if latest_action_buy and not latest_action_sell:
                qty = compute_quantity(latest_open)
                print(f"[{now}] BUY signal detected. Entering LONG x{qty}")
                response = client.placesmartorder(
                    strategy="Bot6bbb_DTC", symbol=SYMBOL, action="BUY",
                    exchange=EXCHANGE, price_type="MARKET", product="MIS",
                    quantity=qty, position_size=qty
                )
                print(f"Entry Order Response: {response}")
                position = Position(symbol=SYMBOL, side=Side.LONG, entry_price=latest_open, qty=qty, entry_time=pd.Timestamp(now))
            
            elif latest_action_sell and not latest_action_buy:
                qty = compute_quantity(latest_open)
                print(f"[{now}] SELL signal detected. Entering SHORT x{qty}")
                response = client.placesmartorder(
                    strategy="Bot6bbb_DTC", symbol=SYMBOL, action="SELL",
                    exchange=EXCHANGE, price_type="MARKET", product="MIS",
                    quantity=qty, position_size=qty * -1
                )
                print(f"Entry Order Response: {response}")
                position = Position(symbol=SYMBOL, side=Side.SHORT, entry_price=latest_open, qty=qty, entry_time=pd.Timestamp(now))
            else:
                pass # No actionable signal on this bar
                
            time.sleep(10) # Wait 10s before next history check when idle
            
        except KeyboardInterrupt:
            print("Strategy stopped by user")
            break
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
