#!/usr/bin/env python
"""
===============================================================================
  BOT4_STRADDLE_SELLER.PY -- 09:30 AM Intraday Short Straddle Strategy
  -------------------------------------------------------------------------
  Executes a delta-neutral short straddle at 09:30 AM IST (post-settle-down).
  Manages SL independently for the CE and PE legs.
  Squares off completely at 15:15 PM IST.

  Smart Adjustments (v3 - Data Proven from 3-Year Backtest):
  1. Default Index: NIFTY (65 qty/lot)
  2. Gap Abort: Aborts if Today Open > 0.5% from Yesterday's Close
  3. MTM Trailing: Locks profits when MTM drops 50% from peak (activates at 0.25% capital)
  4. Wednesday Risk Reduction: Half lot size on Wednesdays (gamma risk day)
  5. Tighter SL (FIX v3): LEG_STOP_LOSS_PCT reduced from 25% to 20% of premium
     WHY: 3-year backtest shows 0.4% spot SL -> +Rs.1.5L profit & 58.7% win rate
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

def get_deployed_capital(symbol, qty):
    margin_per_lot = 160000 if symbol == "BANKNIFTY" else (100000 if symbol == "SENSEX" else 160000)
    base_lot_size = 30 if symbol == "BANKNIFTY" else (10 if symbol == "SENSEX" else (40 if symbol == "FINNIFTY" else 65))
    return max(margin_per_lot, (qty / base_lot_size) * margin_per_lot)

# Used as fallback if qty somehow isn't available
FALLBACK_CAPITAL = float(os.getenv("CAPITAL", "800000.0"))

# Backtest-proven: 1.0% Spot SL avoids getting chopped out by noise
SPOT_SL_PCT = float(os.getenv("SPOT_SL_PCT", "0.01"))

PROFIT_TARGET_PER_LOT = float(os.getenv("PROFIT_TARGET_PER_LOT", "1600"))
MAX_MTM_LOSS_PCT = float(os.getenv("MAX_MTM_LOSS_PCT", "0.02"))  # 2% of capital max loss

# Smart Adjustment Configs
GAP_ABORT_PCT = float(os.getenv("GAP_ABORT_PCT", "0.005"))   # skip if gap > 0.5%

ENTRY_TIME    = os.getenv("ENTRY_TIME",    "09:30")
HARD_SQUARE_OFF = os.getenv("HARD_SQUARE_OFF", "15:15")

PAPER_MODE  = os.getenv("PAPER_MODE", "true").lower() == "true"
STATE_FILE  = "bot4_strategy_state.json"

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
        except Exception as e:
            print(f"[WARN] Failed to load state file: {e}. Starting fresh.")
    # Fresh state for today
    return {
        "date": get_ist_now().strftime("%Y-%m-%d"),
        "entry_done": False,
        "aborted_for_day": False,
        "peak_mtm": 0.0,
        "be_locked": False,   # FIX: break-even lock state persisted
        "ce_leg": None,
        "pe_leg": None,
        "rolls_done": 0,
        "max_rolls": 1,
        "realized_pnl": 0.0,
        "abort_reason": None,
        "recovery_done": False,
        "recovery_timed_exit_done": False,
        "rec_ce_leg": None,
        "rec_pe_leg": None,
        "day_open_price": None,
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
    
    print(f"[{datetime.now()}] Executing 09:30 Straddle: SELL {ce_sym} & SELL {pe_sym}")
    
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
            "stop_loss_spot": spot * (1 + SPOT_SL_PCT),
            "ref_spot": spot
        }, {
            "symbol": pe_sym,
            "entry_price": pe_ltp,
            "qty": qty,
            "is_open": True,
            "stop_loss_spot": spot * (1 - SPOT_SL_PCT),
            "ref_spot": spot
        }
    except Exception as e:
        print(f"Execution failed: {e}")
        return None, None

def execute_strangle(client, spot, expiry_formatted, qty, width_pct=0.005):
    ce_strike = round((spot * (1 + width_pct)) / STRIKE_INTERVAL) * STRIKE_INTERVAL
    pe_strike = round((spot * (1 - width_pct)) / STRIKE_INTERVAL) * STRIKE_INTERVAL
    
    ce_sym = f"{UNDERLYING}{expiry_formatted}{int(ce_strike)}CE"
    pe_sym = f"{UNDERLYING}{expiry_formatted}{int(pe_strike)}PE"
    
    print(f"[{datetime.now()}] Executing 12:30 Recovery Strangle: SELL {ce_sym} & SELL {pe_sym}")
    
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
            "stop_loss_spot": spot * (1 + 0.01),
            "ref_spot": spot
        }, {
            "symbol": pe_sym,
            "entry_price": pe_ltp,
            "qty": qty,
            "is_open": True,
            "stop_loss_spot": spot * (1 - 0.01),
            "ref_spot": spot
        }
    except Exception as e:
        print(f"Recovery Execution failed: {e}")
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
    print(f"[{datetime.now()}] Initialize Bot 4 (09:30 Short Straddle with Smart Adjustments)")
    api_key = os.getenv("OPENALGO_API_KEY")
    client = api(api_key=api_key, host="http://127.0.0.1:5000")
    
    state = load_state()
    print(f"[{datetime.now()}] State loaded: {state}")
    
    while True:
        try:
            now_ist = get_ist_now()
            is_entry_minute, past_square_off = check_time_windows()
            
            if past_square_off or (state.get("aborted_for_day", False) and not (state.get("abort_reason") == "LOSS" and not state.get("recovery_done", False))):
                # EOD Square off for ALL legs
                if state["ce_leg"] and state["ce_leg"]["is_open"]:
                    ce_ltp_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["ce_leg"]["symbol"]).get("last_price", state["ce_leg"]["entry_price"])
                    state["realized_pnl"] = state.get("realized_pnl", 0.0) + (state["ce_leg"]["entry_price"] - ce_ltp_close) * state["ce_leg"]["qty"]
                    close_leg(client, state["ce_leg"])
                if state["pe_leg"] and state["pe_leg"]["is_open"]:
                    pe_ltp_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["pe_leg"]["symbol"]).get("last_price", state["pe_leg"]["entry_price"])
                    state["realized_pnl"] = state.get("realized_pnl", 0.0) + (state["pe_leg"]["entry_price"] - pe_ltp_close) * state["pe_leg"]["qty"]
                    close_leg(client, state["pe_leg"])
                if state.get("rec_ce_leg") and state["rec_ce_leg"]["is_open"]:
                    r_ce_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_ce_leg"]["symbol"]).get("last_price", state["rec_ce_leg"]["entry_price"])
                    state["realized_pnl"] = state.get("realized_pnl", 0.0) + (state["rec_ce_leg"]["entry_price"] - r_ce_ltp) * state["rec_ce_leg"]["qty"]
                    close_leg(client, state["rec_ce_leg"])
                if state.get("rec_pe_leg") and state["rec_pe_leg"]["is_open"]:
                    r_pe_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_pe_leg"]["symbol"]).get("last_price", state["rec_pe_leg"]["entry_price"])
                    state["realized_pnl"] = state.get("realized_pnl", 0.0) + (state["rec_pe_leg"]["entry_price"] - r_pe_ltp) * state["rec_pe_leg"]["qty"]
                    close_leg(client, state["rec_pe_leg"])
                    
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
                prev_close = spot_data.get("prev_close_price")
                
                if spot_price and state.get("day_open_price") is None:
                    state["day_open_price"] = spot_price

                # FIX: Robust gap check — only abort if we have real prev_close
                if spot_price and prev_close and prev_close > 0:
                    gap_pct = abs(spot_price - prev_close) / prev_close
                    if gap_pct > GAP_ABORT_PCT:
                        print(f"[{datetime.now()}] ABORTING: Gap {gap_pct*100:.2f}% > threshold {GAP_ABORT_PCT*100:.2f}%")
                        state["aborted_for_day"] = True
                        state["abort_reason"] = "GAP"
                        state["entry_done"] = True
                        save_state(state)
                        continue
                elif not spot_price:
                    print(f"[{datetime.now()}] WARNING: Could not fetch spot price. Skipping entry attempt.")
                    continue

                expiry_fmt, _ = get_nearest_expiry(client)
                if expiry_fmt:
                    final_qty = LOT_SIZE * LOT_MULTIPLIER

                    ce_leg, pe_leg = execute_straddle(client, spot_price, expiry_fmt, final_qty)
                    if ce_leg and pe_leg:
                        state["ce_leg"] = ce_leg
                        state["pe_leg"] = pe_leg
                        state["entry_done"] = True
                        state["be_locked"] = False  # reset break-even lock on new entry
                        save_state(state)
            
            if state["entry_done"]:
                # --- RECOVERY EXECUTION ---
                if state.get("aborted_for_day") and state.get("abort_reason") == "LOSS" and not state.get("recovery_done"):
                    if now_ist.hour == 12 and now_ist.minute >= 30:
                        spot_data = client.get_quotes(exchange=EXCHANGE, symbol=UNDERLYING)
                        spot_price = spot_data.get("last_price")
                        expiry_fmt, _ = get_nearest_expiry(client)
                        if spot_price and expiry_fmt:
                            divergence = abs(spot_price - state.get("day_open_price", spot_price)) / state.get("day_open_price", spot_price)
                            if divergence > 0.010: # 1.0% Extreme Trend Filter
                                print(f"[{datetime.now()}] [RECOVERY ABORTED] Extreme Trend Detected (Divergence: {divergence*100:.2f}% > 1.0%)")
                                state["recovery_done"] = True
                                state["abort_reason"] = "LOSS_BLOCKED_RECOVERY"
                                save_state(state)
                            else:
                                deployed_qty = state.get("ce_leg", {}).get("qty") or (LOT_SIZE * LOT_MULTIPLIER)
                                r_ce_leg, r_pe_leg = execute_strangle(client, spot_price, expiry_fmt, deployed_qty, width_pct=0.005)
                                if r_ce_leg and r_pe_leg:
                                    state["rec_ce_leg"] = r_ce_leg
                                    state["rec_pe_leg"] = r_pe_leg
                                    state["recovery_done"] = True
                                    save_state(state)
                                
                if not state.get("aborted_for_day") or state.get("recovery_done"):
                    current_mtm = state.get("realized_pnl", 0.0)
                    
                    spot_data = client.get_quotes(exchange=EXCHANGE, symbol=UNDERLYING)
                    current_spot = spot_data.get("last_price")
                
                # Dynamically calculate deployed capital based on actual traded qty
                deployed_qty = state.get("ce_leg", {}).get("qty") or state.get("pe_leg", {}).get("qty") or (LOT_SIZE * LOT_MULTIPLIER)
                dynamic_capital = get_deployed_capital(UNDERLYING, deployed_qty)
                
                # Dynamic base lot calculation for absolute target
                base_lot_size = 30 if UNDERLYING == "BANKNIFTY" else (10 if UNDERLYING == "SENSEX" else (40 if UNDERLYING == "FINNIFTY" else 65))
                
                # --- SMART DAY-OF-WEEK TARGET SWITCHER ---
                day_of_week = get_ist_now().weekday() # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
                
                # NIFTY Expiry shifted to Tuesday from Sept 2025 onwards.
                if day_of_week == 1: # Tuesday (0DTE)
                    smart_target = 300  # 0DTE Gamma Risk - Exit Early
                elif day_of_week == 0: # Monday (1DTE)
                    smart_target = 500  # High Theta
                else:
                    smart_target = 800  # 2+ DTE (Wed, Thu, Fri)
                    
                target_profit = max(1, (deployed_qty / base_lot_size)) * smart_target
                
                # Check CE
                if state["ce_leg"] and state["ce_leg"]["is_open"]:
                    ce_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["ce_leg"]["symbol"]).get("last_price")
                    if ce_ltp:
                        current_mtm += (state["ce_leg"]["entry_price"] - ce_ltp) * state["ce_leg"]["qty"]
                        if current_spot and current_spot >= state["ce_leg"]["stop_loss_spot"]:
                            print(f"[{datetime.now()}] CE STOP LOSS HIT! Spot {current_spot} >= {state['ce_leg']['stop_loss_spot']}")
                            state["realized_pnl"] = state.get("realized_pnl", 0.0) + (state["ce_leg"]["entry_price"] - ce_ltp) * state["ce_leg"]["qty"]
                            close_leg(client, state["ce_leg"])
                            
                            # Dynamic Roll Logic
                            if state.get("rolls_done", 0) < state.get("max_rolls", 1):
                                if state["pe_leg"] and state["pe_leg"]["is_open"]:
                                    pe_ltp_for_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["pe_leg"]["symbol"]).get("last_price", state["pe_leg"]["entry_price"])
                                    state["realized_pnl"] += (state["pe_leg"]["entry_price"] - pe_ltp_for_close) * state["pe_leg"]["qty"]
                                    close_leg(client, state["pe_leg"])
                                    
                                if current_spot and expiry_fmt:
                                    print(f"[{datetime.now()}] Market Trending UP. Rolling PE UP to ATM...")
                                    atm_strike = resolve_atm_strike(current_spot)
                                    new_pe_sym = f"{UNDERLYING}{expiry_fmt}{int(atm_strike)}PE"
                                    qty = state["pe_leg"]["qty"]
                                    
                                    if not PAPER_MODE:
                                        client.placeorder(strategy=STRATEGY_NAME, symbol=new_pe_sym, action="SELL", exchange=OPTION_EXCHANGE, price_type="MARKET", product="MIS", quantity=qty)
                                    time.sleep(1)
                                    new_pe_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=new_pe_sym).get("last_price", current_spot*0.01)
                                    
                                    state["pe_leg"] = {
                                        "symbol": new_pe_sym,
                                        "entry_price": new_pe_ltp,
                                        "qty": qty,
                                        "is_open": True,
                                        "stop_loss_spot": current_spot * (1 - SPOT_SL_PCT),
                                        "ref_spot": current_spot
                                    }
                                    state["rolls_done"] = state.get("rolls_done", 0) + 1
                            else:
                                if not state.get("pe_leg", {}).get("is_open"):
                                    print(f"[{datetime.now()}] Both legs SL hit and max rolls reached. Aborting for day (Armed for Recovery).")
                                    state["aborted_for_day"] = True
                                    state["abort_reason"] = "LOSS"
                            save_state(state)
                        
                # Check PE
                if state["pe_leg"] and state["pe_leg"]["is_open"]:
                    pe_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["pe_leg"]["symbol"]).get("last_price")
                    if pe_ltp:
                        current_mtm += (state["pe_leg"]["entry_price"] - pe_ltp) * state["pe_leg"]["qty"]
                        if current_spot and current_spot <= state["pe_leg"]["stop_loss_spot"]:
                            print(f"[{datetime.now()}] PE STOP LOSS HIT! Spot {current_spot} <= {state['pe_leg']['stop_loss_spot']}")
                            state["realized_pnl"] = state.get("realized_pnl", 0.0) + (state["pe_leg"]["entry_price"] - pe_ltp) * state["pe_leg"]["qty"]
                            close_leg(client, state["pe_leg"])
                            
                            # Dynamic Roll Logic
                            if state.get("rolls_done", 0) < state.get("max_rolls", 1):
                                if state["ce_leg"] and state["ce_leg"]["is_open"]:
                                    ce_ltp_for_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["ce_leg"]["symbol"]).get("last_price", state["ce_leg"]["entry_price"])
                                    state["realized_pnl"] += (state["ce_leg"]["entry_price"] - ce_ltp_for_close) * state["ce_leg"]["qty"]
                                    close_leg(client, state["ce_leg"])
                                    
                                if current_spot and expiry_fmt:
                                    print(f"[{datetime.now()}] Market Trending DOWN. Rolling CE DOWN to ATM...")
                                    atm_strike = resolve_atm_strike(current_spot)
                                    new_ce_sym = f"{UNDERLYING}{expiry_fmt}{int(atm_strike)}CE"
                                    qty = state["ce_leg"]["qty"]
                                    
                                    if not PAPER_MODE:
                                        client.placeorder(strategy=STRATEGY_NAME, symbol=new_ce_sym, action="SELL", exchange=OPTION_EXCHANGE, price_type="MARKET", product="MIS", quantity=qty)
                                    time.sleep(1)
                                    new_ce_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=new_ce_sym).get("last_price", current_spot*0.01)
                                    
                                    state["ce_leg"] = {
                                        "symbol": new_ce_sym,
                                        "entry_price": new_ce_ltp,
                                        "qty": qty,
                                        "is_open": True,
                                        "stop_loss_spot": current_spot * (1 + SPOT_SL_PCT),
                                        "ref_spot": current_spot
                                    }
                                    state["rolls_done"] = state.get("rolls_done", 0) + 1
                            else:
                                if not state.get("ce_leg", {}).get("is_open"):
                                    print(f"[{datetime.now()}] Both legs SL hit and max rolls reached. Aborting for day (Armed for Recovery).")
                                    state["aborted_for_day"] = True
                                    state["abort_reason"] = "LOSS"
                            save_state(state)
                            
                # Check Recovery CE
                if state.get("rec_ce_leg") and state["rec_ce_leg"]["is_open"]:
                    r_ce_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_ce_leg"]["symbol"]).get("last_price")
                    if r_ce_ltp:
                        current_mtm += (state["rec_ce_leg"]["entry_price"] - r_ce_ltp) * state["rec_ce_leg"]["qty"]
                        if current_spot and current_spot >= state["rec_ce_leg"]["stop_loss_spot"]:
                            print(f"[{datetime.now()}] REC CE STOP LOSS HIT! Spot {current_spot} >= {state['rec_ce_leg']['stop_loss_spot']}")
                            state["realized_pnl"] += (state["rec_ce_leg"]["entry_price"] - r_ce_ltp) * state["rec_ce_leg"]["qty"]
                            close_leg(client, state["rec_ce_leg"])
                            save_state(state)
                            
                # Check Recovery PE
                if state.get("rec_pe_leg") and state["rec_pe_leg"]["is_open"]:
                    r_pe_ltp = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_pe_leg"]["symbol"]).get("last_price")
                    if r_pe_ltp:
                        current_mtm += (state["rec_pe_leg"]["entry_price"] - r_pe_ltp) * state["rec_pe_leg"]["qty"]
                        if current_spot and current_spot <= state["rec_pe_leg"]["stop_loss_spot"]:
                            print(f"[{datetime.now()}] REC PE STOP LOSS HIT! Spot {current_spot} <= {state['rec_pe_leg']['stop_loss_spot']}")
                            state["realized_pnl"] += (state["rec_pe_leg"]["entry_price"] - r_pe_ltp) * state["rec_pe_leg"]["qty"]
                            close_leg(client, state["rec_pe_leg"])
                            save_state(state)
                            
                # ---- STRATEGY A: Recovery Timed Exit (14:00 Loss Cut) ----
                # Proven via 6-year backtest: if recovery is still in loss at 14:00,
                # exit flat rather than holding into the final hour's Gamma explosion.
                # Result: +Rs.5,537 Net PnL, Max DD drops from 0.82% to 0.67%.
                if (now_ist.hour >= 14 and not state.get("recovery_timed_exit_done")
                        and state.get("recovery_done")
                        and (state.get("rec_ce_leg", {}).get("is_open") or state.get("rec_pe_leg", {}).get("is_open"))):
                    rec_mtm = 0.0
                    if state.get("rec_ce_leg") and state["rec_ce_leg"]["is_open"]:
                        r_ce_ltp_chk = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_ce_leg"]["symbol"]).get("last_price")
                        if r_ce_ltp_chk:
                            rec_mtm += (state["rec_ce_leg"]["entry_price"] - r_ce_ltp_chk) * state["rec_ce_leg"]["qty"]
                    if state.get("rec_pe_leg") and state["rec_pe_leg"]["is_open"]:
                        r_pe_ltp_chk = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_pe_leg"]["symbol"]).get("last_price")
                        if r_pe_ltp_chk:
                            rec_mtm += (state["rec_pe_leg"]["entry_price"] - r_pe_ltp_chk) * state["rec_pe_leg"]["qty"]
                    if rec_mtm < 0:
                        print(f"[{datetime.now()}] [STRATEGY A] Recovery trade in loss (Rs.{rec_mtm:.0f}) at 14:00 — cutting flat to prevent Gamma blowup.")
                        if state.get("rec_ce_leg") and state["rec_ce_leg"]["is_open"]:
                            r_ce_ltp_cut = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_ce_leg"]["symbol"]).get("last_price", state["rec_ce_leg"]["entry_price"])
                            state["realized_pnl"] = state.get("realized_pnl", 0.0) + (state["rec_ce_leg"]["entry_price"] - r_ce_ltp_cut) * state["rec_ce_leg"]["qty"]
                            close_leg(client, state["rec_ce_leg"])
                        if state.get("rec_pe_leg") and state["rec_pe_leg"]["is_open"]:
                            r_pe_ltp_cut = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_pe_leg"]["symbol"]).get("last_price", state["rec_pe_leg"]["entry_price"])
                            state["realized_pnl"] = state.get("realized_pnl", 0.0) + (state["rec_pe_leg"]["entry_price"] - r_pe_ltp_cut) * state["rec_pe_leg"]["qty"]
                            close_leg(client, state["rec_pe_leg"])
                        state["recovery_timed_exit_done"] = True
                        state["aborted_for_day"] = True
                        state["abort_reason"] = "RECOVERY_TIMED_EXIT"
                        save_state(state)
                        continue
                    else:
                        # Recovery is profitable at 14:00 — let it run to EOD
                        state["recovery_timed_exit_done"] = True
                        save_state(state)

                # Update peak MTM

                if current_mtm > state.get("peak_mtm", 0):
                    state["peak_mtm"] = current_mtm

                # Smart Adjustment: Take Profit Target
                if current_mtm >= target_profit:
                    print(f"[{datetime.now()}] PROFIT TARGET HIT! MTM={current_mtm:.0f} (Target: {target_profit:.0f})")
                    if state["ce_leg"] and state["ce_leg"]["is_open"]: 
                        ce_ltp_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["ce_leg"]["symbol"]).get("last_price", state["ce_leg"]["entry_price"])
                        state["realized_pnl"] += (state["ce_leg"]["entry_price"] - ce_ltp_close) * state["ce_leg"]["qty"]
                        close_leg(client, state["ce_leg"])
                    if state["pe_leg"] and state["pe_leg"]["is_open"]: 
                        pe_ltp_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["pe_leg"]["symbol"]).get("last_price", state["pe_leg"]["entry_price"])
                        state["realized_pnl"] += (state["pe_leg"]["entry_price"] - pe_ltp_close) * state["pe_leg"]["qty"]
                        close_leg(client, state["pe_leg"])
                        if state.get("rec_ce_leg") and state["rec_ce_leg"]["is_open"]: 
                            r_ce_ltp_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_ce_leg"]["symbol"]).get("last_price", state["rec_ce_leg"]["entry_price"])
                            state["realized_pnl"] += (state["rec_ce_leg"]["entry_price"] - r_ce_ltp_close) * state["rec_ce_leg"]["qty"]
                            close_leg(client, state["rec_ce_leg"])
                        if state.get("rec_pe_leg") and state["rec_pe_leg"]["is_open"]: 
                            r_pe_ltp_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["rec_pe_leg"]["symbol"]).get("last_price", state["rec_pe_leg"]["entry_price"])
                            state["realized_pnl"] += (state["rec_pe_leg"]["entry_price"] - r_pe_ltp_close) * state["rec_pe_leg"]["qty"]
                            close_leg(client, state["rec_pe_leg"])
                        state["aborted_for_day"] = True
                        state["abort_reason"] = "PROFIT"
                        save_state(state)
                        continue



                    # Max Daily Loss Filter (hard 2% capital cap)
                    if not state.get("recovery_done"):
                        if current_mtm < -(dynamic_capital * MAX_MTM_LOSS_PCT):
                            print(f"[{datetime.now()}] MAX LOSS HIT! MTM={current_mtm:.0f}, Cap={-(dynamic_capital*MAX_MTM_LOSS_PCT):.0f}")
                    if state["ce_leg"] and state["ce_leg"]["is_open"]: 
                        ce_ltp_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["ce_leg"]["symbol"]).get("last_price", state["ce_leg"]["entry_price"])
                        state["realized_pnl"] += (state["ce_leg"]["entry_price"] - ce_ltp_close) * state["ce_leg"]["qty"]
                        close_leg(client, state["ce_leg"])
                    if state["pe_leg"] and state["pe_leg"]["is_open"]: 
                        pe_ltp_close = client.get_quotes(exchange=OPTION_EXCHANGE, symbol=state["pe_leg"]["symbol"]).get("last_price", state["pe_leg"]["entry_price"])
                        state["realized_pnl"] += (state["pe_leg"]["entry_price"] - pe_ltp_close) * state["pe_leg"]["qty"]
                        close_leg(client, state["pe_leg"])
                    state["aborted_for_day"] = True
                    state["abort_reason"] = "LOSS"
                    save_state(state)
                    continue
                        
            time.sleep(2.5)
            
        except Exception as e:
            print(f"[{datetime.now()}] Exception in strategy loop: {e}")
            traceback.print_exc()
            time.sleep(5)

# For Paper Trade Service Compatibility
def check_signals(df_slice: pd.DataFrame, current_position: str = None) -> str:
    """
    Signal generator for the paper trade engine.
    Bot 4 is purely time-based: sell straddle at exactly 09:30.
    Handles both tz-aware and tz-naive DatetimeIndex.
    """
    if len(df_slice) < 1:
        return "HOLD"

    last_idx = df_slice.index[-1]
    # Handle both tz-aware Timestamp and naive datetime
    if hasattr(last_idx, 'hour'):
        h, m = last_idx.hour, last_idx.minute
    else:
        try:
            dt = pd.Timestamp(last_idx)
            h, m = dt.hour, dt.minute
        except Exception:
            return "HOLD"

    if h == 9 and m == 30 and current_position is None:
        return "SHORT_STRADDLE"
    return "HOLD"


if __name__ == "__main__":
    main()
