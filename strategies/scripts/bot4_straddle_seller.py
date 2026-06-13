#!/usr/bin/env python
"""
===============================================================================
  BOT4_STRADDLE_SELLER.PY -- 9:20 AM Intraday Short Straddle Strategy
  ---------------------------------------------------------------------
  Executes a delta-neutral short straddle strictly at 9:20 AM IST.
  Manages 25% stop-losses independently for the CE and PE legs.
  Squares off completely at 15:15 PM IST.
  
  Smart Adjustments Implemented:
  1. Default Index: NIFTY
  2. Gap Abort: Aborts if Open > 0.5% from Prev Close
  3. MTM Trailing: Locks in profits if MTM drops 50% from its peak.
===============================================================================
"""

import os
import sys
import time
import json
import traceback
from datetime import datetime, timezone, timedelta, time as time_obj
import pandas as pd

from openalgo import api

STRATEGY_NAME = os.getenv("STRATEGY_NAME", "Bot4_Short_Straddle")
UNDERLYING = os.getenv("UNDERLYING", "NIFTY")
EXCHANGE = os.getenv("OPENALGO_STRATEGY_EXCHANGE", os.getenv("EXCHANGE", "NSE_INDEX"))
OPTION_EXCHANGE = os.getenv("OPTION_EXCHANGE", "NFO")
EXECUTION_MODE = "options_selling"

def _get_default_param(param_name, underlying):
    if param_name == "LOT_SIZE":
        if underlying == "NIFTY": return 65
        elif underlying == "BANKNIFTY": return 30
        elif underlying == "FINNIFTY": return 60
        elif underlying == "MIDCPNIFTY": return 120
        return 30
    elif param_name == "STRIKE_INTERVAL":
        if underlying == "NIFTY": return 50
        elif underlying == "BANKNIFTY": return 100
        elif underlying == "FINNIFTY": return 100
        return 100
    return 0

LOT_SIZE = int(os.getenv("LOT_SIZE", str(_get_default_param("LOT_SIZE", UNDERLYING))))
LOT_MULTIPLIER = int(os.getenv("LOT_MULTIPLIER", "1"))
STRIKE_INTERVAL = int(os.getenv("STRIKE_INTERVAL", str(_get_default_param("STRIKE_INTERVAL", UNDERLYING))))

CAPITAL = float(os.getenv("CAPITAL", "800000.0"))
LEG_STOP_LOSS_PCT = float(os.getenv("LEG_STOP_LOSS_PCT", "0.25"))
MAX_MTM_LOSS_PCT = float(os.getenv("MAX_MTM_LOSS_PCT", "0.02")) # 2% of capital max loss

# Smart Adjustment Configs
GAP_ABORT_PCT = float(os.getenv("GAP_ABORT_PCT", "0.005"))
MTM_TRAIL_START_PCT = float(os.getenv("MTM_TRAIL_START_PCT", "0.005"))

ENTRY_TIME = os.getenv("ENTRY_TIME", "09:21")
HARD_SQUARE_OFF = os.getenv("HARD_SQUARE_OFF", "15:15")

PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
STATE_FILE = "bot4_strategy_state.json"

IST = timezone(timedelta(hours=5, minutes=30))

def get_ist_now():
    return datetime.now(IST)

def check_time_windows():
    now_time = get_ist_now().time()
    def to_time(t_str):
        h, m = map(int, t_str.split(":"))
        return time_obj(h, m)
        
    entry = to_time(ENTRY_TIME)
    square_off = to_time(HARD_SQUARE_OFF)
    
    is_entry_minute = (now_time.hour == entry.hour and now_time.minute >= entry.minute) and now_time < square_off
    past_square_off = (now_time >= square_off)
    return is_entry_minute, past_square_off

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                state_date = state.get("date")
                if state_date == get_ist_now().strftime("%Y-%m-%d"):
                    return state
        except:
            pass
    return {
        "date": get_ist_now().strftime("%Y-%m-%d"),
        "entry_done": False,
        "aborted_for_day": False,
        "peak_mtm": 0.0,
        "ce_leg": None,
        "pe_leg": None,
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def resolve_atm_strike(spot):
    return round(spot / STRIKE_INTERVAL) * STRIKE_INTERVAL

def get_nearest_expiry(client):
    try:
        sym_info = client.get_symbols(exchange=OPTION_EXCHANGE, underlying=UNDERLYING)
        df = pd.DataFrame(sym_info)
        if df.empty: return None, None
        df['expiry'] = pd.to_datetime(df['expiry'])
        nearest = df[df['expiry'] >= pd.Timestamp(get_ist_now().date())].sort_values('expiry').iloc[0]
        return nearest['expiry'].strftime("%y%b").upper(), nearest['expiry'].strftime("%Y-%m-%d")
    except Exception as e:
        print(f"Error fetching expiry: {e}")
        return None, None

def execute_straddle(client, spot, expiry_formatted, qty):
    atm_strike = resolve_atm_strike(spot)
    ce_sym = f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE"
    pe_sym = f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}PE"
    
    print(f"[{datetime.now()}] Executing 9:20 Straddle: SELL {ce_sym} & SELL {pe_sym}")
    
    try:
        if not PAPER_MODE:
            client.placeorder(strategy=STRATEGY_NAME, symbol=ce_sym, action="SELL", exchange=OPTION_EXCHANGE, price_type="MARKET", product="MIS", quantity=qty)
            client.placeorder(strategy=STRATEGY_NAME, symbol=pe_sym, action="SELL", exchange=OPTION_EXCHANGE, price_type="MARKET", product="MIS", quantity=qty)
        
        time.sleep(1) 
        ce_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=ce_sym).get("last_price", spot*0.01)
        pe_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=pe_sym).get("last_price", spot*0.01)
        
        return {
            "symbol": ce_sym,
            "entry_price": ce_ltp,
            "qty": qty,
            "is_open": True,
            "stop_loss": ce_ltp * (1 + LEG_STOP_LOSS_PCT)
        }, {
            "symbol": pe_sym,
            "entry_price": pe_ltp,
            "qty": qty,
            "is_open": True,
            "stop_loss": pe_ltp * (1 + LEG_STOP_LOSS_PCT)
        }
    except Exception as e:
        print(f"Execution failed: {e}")
        return None, None

def close_leg(client, leg):
    print(f"[{datetime.now()}] Closing leg: {leg['symbol']}")
    if not PAPER_MODE:
        try:
            client.placeorder(strategy=STRATEGY_NAME, symbol=leg['symbol'], action="BUY", exchange=OPTION_EXCHANGE, price_type="MARKET", product="MIS", quantity=leg['qty'])
        except Exception as e:
            print(f"Error closing leg: {e}")
    leg["is_open"] = False
    return leg

def main():
    print(f"[{datetime.now()}] Initialize Bot 4 (9:20 Short Straddle with Smart Adjustments)")
    api_key = os.getenv("OPENALGO_API_KEY")
    client = api(api_key=api_key, host="http://127.0.0.1:5000")
    
    state = load_state()
    print(f"[{datetime.now()}] State loaded: {state}")
    
    while True:
        try:
            now_ist = get_ist_now()
            is_entry_minute, past_square_off = check_time_windows()
            
            if past_square_off or state.get("aborted_for_day", False):
                if state["ce_leg"] and state["ce_leg"]["is_open"]:
                    close_leg(client, state["ce_leg"])
                if state["pe_leg"] and state["pe_leg"]["is_open"]:
                    close_leg(client, state["pe_leg"])
                state["entry_done"] = True
                save_state(state)
                
                if past_square_off:
                    print(f"[{datetime.now()}] EOD Square Off Complete. Exiting loop.")
                    time.sleep(60)
                else:
                    time.sleep(10)
                continue
                
            if is_entry_minute and not state["entry_done"]:
                spot_data = client.get_quotes(exchange=EXCHANGE, symbol=UNDERLYING)
                spot_price = spot_data.get("last_price")
                prev_close = spot_data.get("prev_close_price", spot_price)
                
                if spot_price and prev_close:
                    # Smart Adjustment 2: Gap-Up Abort Logic
                    gap_pct = abs(spot_price - prev_close) / prev_close
                    if gap_pct > GAP_ABORT_PCT:
                        print(f"[{datetime.now()}] ABORTING: Massive Gap Detected ({gap_pct*100:.2f}% > {GAP_ABORT_PCT*100:.2f}%)")
                        state["aborted_for_day"] = True
                        state["entry_done"] = True
                        save_state(state)
                        continue
                        
                    expiry_fmt, _ = get_nearest_expiry(client)
                    if expiry_fmt:
                        # Smart Adjustment 4: Wednesday Risk Reduction
                        current_multiplier = LOT_MULTIPLIER
                        if now_ist.weekday() == 2: # Wednesday
                            print(f"[{datetime.now()}] Wednesday detected. Halving risk exposure.")
                            current_multiplier = max(1, current_multiplier // 2)
                        final_qty = LOT_SIZE * current_multiplier
                        
                        ce_leg, pe_leg = execute_straddle(client, spot_price, expiry_fmt, final_qty)
                        if ce_leg and pe_leg:
                            state["ce_leg"] = ce_leg
                            state["pe_leg"] = pe_leg
                            state["entry_done"] = True
                            save_state(state)
            
            if state["entry_done"] and not state.get("aborted_for_day"):
                current_mtm = 0
                
                # Check CE
                if state["ce_leg"] and state["ce_leg"]["is_open"]:
                    ce_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["ce_leg"]["symbol"]).get("last_price")
                    if ce_ltp:
                        current_mtm += (state["ce_leg"]["entry_price"] - ce_ltp) * state["ce_leg"]["qty"]
                        if ce_ltp >= state["ce_leg"]["stop_loss"]:
                            print(f"[{datetime.now()}] CE STOP LOSS HIT! {ce_ltp} >= {state['ce_leg']['stop_loss']}")
                            close_leg(client, state["ce_leg"])
                            save_state(state)
                        
                # Check PE
                if state["pe_leg"] and state["pe_leg"]["is_open"]:
                    pe_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["pe_leg"]["symbol"]).get("last_price")
                    if pe_ltp:
                        current_mtm += (state["pe_leg"]["entry_price"] - pe_ltp) * state["pe_leg"]["qty"]
                        if pe_ltp >= state["pe_leg"]["stop_loss"]:
                            print(f"[{datetime.now()}] PE STOP LOSS HIT! {pe_ltp} >= {state['pe_leg']['stop_loss']}")
                            close_leg(client, state["pe_leg"])
                            save_state(state)
                            
                # Smart Adjustment 3: MTM Profit Trailing
                if current_mtm > state.get("peak_mtm", 0):
                    state["peak_mtm"] = current_mtm
                    
                if state.get("peak_mtm", 0) > (CAPITAL * MTM_TRAIL_START_PCT):
                    if current_mtm < (state["peak_mtm"] * 0.5):
                        print(f"[{datetime.now()}] MTM TRAILING STOP HIT! Dropped to {current_mtm} from peak {state['peak_mtm']}")
                        if state["ce_leg"] and state["ce_leg"]["is_open"]: close_leg(client, state["ce_leg"])
                        if state["pe_leg"] and state["pe_leg"]["is_open"]: close_leg(client, state["pe_leg"])
                        state["aborted_for_day"] = True
                        save_state(state)
                        
                # Max Daily Loss Filter
                if current_mtm < -(CAPITAL * MAX_MTM_LOSS_PCT):
                    print(f"[{datetime.now()}] SYSTEM MAX LOSS HIT! MTM: {current_mtm}")
                    if state["ce_leg"] and state["ce_leg"]["is_open"]: close_leg(client, state["ce_leg"])
                    if state["pe_leg"] and state["pe_leg"]["is_open"]: close_leg(client, state["pe_leg"])
                    state["aborted_for_day"] = True
                    save_state(state)
                        
            time.sleep(2.5)
            
        except Exception as e:
            print(f"[{datetime.now()}] Exception in strategy loop: {e}")
            traceback.print_exc()
            time.sleep(5)

# For Paper Trade Service Compatibility
def check_signals(df_slice: pd.DataFrame, current_position: str = None) -> str:
    """Mock for paper trade engine. Bot 4 logic is purely time-based."""
    if len(df_slice) < 1:
        return "HOLD"
        
    last_candle_time = df_slice.index[-1]
    if last_candle_time.hour == 9 and last_candle_time.minute == 21:
        return "SHORT_STRADDLE"
    return "HOLD"

if __name__ == "__main__":
    main()
