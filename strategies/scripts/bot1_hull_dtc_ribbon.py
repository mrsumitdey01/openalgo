#!/usr/bin/env python
"""
===============================================================================
  BOT1_HULL_DTC_RIBBON.PY -- Hull BBI + DTC Ribbon Option Spread Strategy
  ---------------------------------------------------------------------
  Recreated in the current OpenAlgo Python strategy host framework.

  Features:
    - 1-minute candle close checks.
    - Hull BBI directional momentum (Length 21).
    - DTC Ribbon Fibonacci EMA Cluster (8, 13, 21, 26, 34, 40).
    - Bull Call Spread (BUY ATM CE + SELL ATM+500 CE) on LONG entries.
    - Bear Put Spread (BUY ATM PE + SELL ATM-500 PE) on SHORT entries.
    - Limit order chasing execution loop (Modify limit orders by steps).
    - Trailing Risk Checks:
        - 15% Spread premium stop-loss.
        - Spot structural stop-loss (Lowest low / Highest high of last 5 candles).
        - 15:15 EOD square-off.
    - Local JSON state tracking for crash recovery.
===============================================================================
"""

import os
import sys
import time
import json
import math
import traceback
from datetime import datetime, timezone, timedelta, time as time_obj
import numpy as np
import pandas as pd

from openalgo import api

# ─────────────────────────────────────────────────────────────────────────────
#  PARAMETERS & CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
STRATEGY_NAME = os.getenv("STRATEGY_NAME", "Bot1_Hull_DTC_Ribbon")
UNDERLYING = os.getenv("UNDERLYING", "BANKNIFTY")
EXCHANGE = os.getenv("OPENALGO_STRATEGY_EXCHANGE", os.getenv("EXCHANGE", "NSE_INDEX"))
OPTION_EXCHANGE = os.getenv("OPTION_EXCHANGE", "NFO")

# Dynamically set index-specific parameter defaults if not overridden by env
def _get_default_param(param_name, underlying):
    if param_name == "LOT_SIZE":
        if underlying == "NIFTY":
            return 65
        elif underlying == "BANKNIFTY":
            return 30
        elif underlying == "FINNIFTY":
            return 60
        elif underlying == "MIDCPNIFTY":
            return 120
        return 30
    elif param_name == "SPREAD_WIDTH":
        if underlying == "NIFTY":
            return 200
        elif underlying == "BANKNIFTY":
            return 500
        elif underlying == "FINNIFTY":
            return 100
        return 500
    elif param_name == "STRIKE_INTERVAL":
        if underlying == "NIFTY":
            return 50
        elif underlying == "BANKNIFTY":
            return 100
        elif underlying == "FINNIFTY":
            return 100
        return 100
    return 0

LOT_SIZE = int(os.getenv("LOT_SIZE", str(_get_default_param("LOT_SIZE", UNDERLYING))))
LOT_MULTIPLIER = int(os.getenv("LOT_MULTIPLIER", "1"))
SPREAD_WIDTH = int(os.getenv("SPREAD_WIDTH", str(_get_default_param("SPREAD_WIDTH", UNDERLYING))))
STRIKE_INTERVAL = int(os.getenv("STRIKE_INTERVAL", str(_get_default_param("STRIKE_INTERVAL", UNDERLYING))))

HMA_LENGTH = int(os.getenv("HMA_LENGTH", "21"))
EMA_LENGTHS = [int(x) for x in os.getenv("EMA_LENGTHS", "8,13,21,26,34,40").split(",")]

SPREAD_STOP_LOSS_PCT = float(os.getenv("SPREAD_STOP_LOSS_PCT", "0.15"))
STRUCTURAL_STOP_LOOKBACK = int(os.getenv("STRUCTURAL_STOP_LOOKBACK", "5"))

TRADE_START = os.getenv("TRADE_START", "09:30")
NO_NEW_ENTRIES = os.getenv("NO_NEW_ENTRIES", "14:45")
HARD_SQUARE_OFF = os.getenv("HARD_SQUARE_OFF", "15:15")

BNF_CHASE_MAX_SLIPPAGE_POINTS = float(os.getenv("BNF_CHASE_MAX_SLIPPAGE_POINTS", "3.00"))
BNF_CHASE_INTERVAL_SECS = float(os.getenv("BNF_CHASE_INTERVAL_SECS", "1.5"))
BNF_CHASE_STEP_POINTS = float(os.getenv("BNF_CHASE_STEP_POINTS", "0.15"))
BNF_CHASE_MAX_RETRIES = int(os.getenv("BNF_CHASE_MAX_RETRIES", "20"))

PAPER_MODE = os.getenv("PAPER_MODE", "true").lower() == "true"
STATE_FILE = "strategy_state.json"

IST = timezone(timedelta(hours=5, minutes=30))

# ─────────────────────────────────────────────────────────────────────────────
#  INDICATOR MATH CLASSES
# ─────────────────────────────────────────────────────────────────────────────

class HullBBI:
    """Hull Moving Average (Length 21) zero-lag momentum."""
    def __init__(self, length=21):
        self.length = length
        self.half_len = round(self.length / 2)
        self.sqrt_len = round(math.sqrt(self.length))

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        wma_half = self._wma(close, self.half_len)
        wma_full = self._wma(close, self.length)
        diff = 2.0 * wma_half - wma_full
        hma = self._wma(diff, self.sqrt_len)
        df["hma"] = hma
        df["hma_prev"] = hma.shift(1)
        df["hma_bullish"] = hma > hma.shift(1)
        df["hma_bearish"] = hma < hma.shift(1)
        return df

    @staticmethod
    def _wma(series: pd.Series, period: int) -> pd.Series:
        weights = np.arange(1, period + 1, dtype=np.float64)
        weight_sum = weights.sum()
        return series.rolling(window=period, min_periods=period).apply(
            lambda x: np.dot(x, weights) / weight_sum,
            raw=True,
        )

class DTCRibbon:
    """DTC Ribbon 6-EMA Fibonacci Cluster (8, 13, 21, 26, 34, 40)."""
    def __init__(self, lengths=[8, 13, 21, 26, 34, 40]):
        self.lengths = lengths

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ema_col_names = []
        for length in self.lengths:
            col = f"ema_{length}"
            df[col] = close.ewm(span=length, adjust=False).mean()
            ema_col_names.append(col)

        ema_matrix = df[ema_col_names]
        df["ribbon_max"] = ema_matrix.max(axis=1)
        df["ribbon_min"] = ema_matrix.min(axis=1)

        bullish = pd.Series(True, index=df.index)
        bearish = pd.Series(True, index=df.index)
        for i in range(len(ema_col_names) - 1):
            bullish = bullish & (df[ema_col_names[i]] > df[ema_col_names[i + 1]])
            bearish = bearish & (df[ema_col_names[i]] < df[ema_col_names[i + 1]])

        df["ribbon_bullish"] = bullish
        df["ribbon_bearish"] = bearish
        df["ribbon_bullish_prev"] = bullish.shift(1).astype(bool).fillna(False)
        df["ribbon_bearish_prev"] = bearish.shift(1).astype(bool).fillna(False)
        df["ribbon_fresh_bull"] = bullish & ~df["ribbon_bullish_prev"]
        df["ribbon_fresh_bear"] = bearish & ~df["ribbon_bearish_prev"]
        return df

# ─────────────────────────────────────────────────────────────────────────────
#  SIGNAL ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def check_signals(df: pd.DataFrame, current_position=None):
    """Evaluates entry/exit logic against the last completed candle."""
    if len(df) < 2:
        return None

    last = get_last_completed_candle(df)
    
    if pd.isna(last.get("hma")):
        return None

    close = float(last["close"])
    hma = float(last["hma"])
    hma_bullish = bool(last["hma_bullish"])
    hma_bearish = bool(last["hma_bearish"])
    ribbon_bullish = bool(last.get("ribbon_bullish", False))
    ribbon_bearish = bool(last.get("ribbon_bearish", False))
    ribbon_max = float(last.get("ribbon_max", 0))
    ribbon_min = float(last.get("ribbon_min", 0))

    is_long_cond = (close > hma) and hma_bullish and (close > ribbon_max)
    is_short_cond = (close < hma) and hma_bearish and (close < ribbon_min)

    if current_position == "LONG":
        # Exit if reverse signal OR basic Hull bear
        if is_short_cond:
            return "EXIT_LONG"
        elif hma_bearish and (close < hma - 5.0):
            return "EXIT_LONG"
            
    elif current_position == "SHORT":
        if is_long_cond:
            return "EXIT_SHORT"
        elif hma_bullish and (close > hma + 5.0):
            return "EXIT_SHORT"
            
    elif current_position is None:
        if is_long_cond:
            return "LONG"
        if is_short_cond:
            return "SHORT"

    return None

# ─────────────────────────────────────────────────────────────────────────────
#  TIME MANAGEMENT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_ist_now():
    """Returns the current localized datetime in Indian Standard Time (IST)."""
    return datetime.now(timezone.utc).astimezone(IST)

def get_last_completed_candle(df: pd.DataFrame) -> pd.Series:
    """Helper to identify the last completed candle dynamically, avoiding in-progress candle repainting."""
    if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 2:
        return df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        
    now_ist = get_ist_now()
    current_minute_start = now_ist.replace(second=0, microsecond=0)
    last_candle_time = df.index[-1]
    
    if last_candle_time.timestamp() >= current_minute_start.timestamp():
        return df.iloc[-2]
    else:
        return df.iloc[-1]

def check_time_windows():
    """Checks whether the bot is inside trading windows or past square-off."""
    now_time = get_ist_now().time()
    
    def to_time(t_str):
        h, m = map(int, t_str.split(":"))
        return time_obj(h, m)
        
    start = to_time(TRADE_START)
    no_new = to_time(NO_NEW_ENTRIES)
    square_off = to_time(HARD_SQUARE_OFF)
    
    in_entry_window = (start <= now_time <= no_new)
    past_square_off = (now_time >= square_off)
    
    return in_entry_window, past_square_off

# ─────────────────────────────────────────────────────────────────────────────
#  STATE FILE PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def save_state(active_spread, stop_level):
    state = {
        "active_spread": active_spread,
        "stop_level": stop_level
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[{datetime.now()}] Error saving state: {e}")

def load_state():
    if not os.path.exists(STATE_FILE):
        return None, None
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            return state.get("active_spread"), state.get("stop_level")
    except Exception as e:
        print(f"[{datetime.now()}] Error loading state: {e}")
        return None, None

def clear_state():
    if os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except Exception as e:
            print(f"[{datetime.now()}] Error clearing state: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  MARKET DATA HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_history(client):
    """Fetches historical 1m data for underlying index spot."""
    try:
        end_date = get_ist_now().strftime("%Y-%m-%d")
        start_date = (get_ist_now() - timedelta(days=5)).strftime("%Y-%m-%d")
        
        df = client.history(
            symbol=UNDERLYING,
            exchange=EXCHANGE,
            interval="1m",
            start_date=start_date,
            end_date=end_date
        )
        if isinstance(df, pd.DataFrame) and not df.empty:
            df['close'] = df['close'].round(2)
            return df
        else:
            print(f"[{datetime.now()}] History query returned empty or invalid data: {df}")
            return None
    except Exception as e:
        print(f"[{datetime.now()}] Error fetching history: {e}")
        return None

def get_nearest_expiry(client):
    """Fetches closest weekly expiry for underlying index options."""
    try:
        res = client.expiry(symbol=UNDERLYING, exchange=OPTION_EXCHANGE, instrumenttype="options")
        if isinstance(res, dict) and res.get("status") == "success":
            expiries = res.get("data", [])
            if expiries:
                nearest = expiries[0]
                formatted = nearest.replace("-", "")
                return formatted, nearest
        print(f"[{datetime.now()}] Failed to get expiries: {res}")
        return None, None
    except Exception as e:
        print(f"[{datetime.now()}] Error fetching expiry dates: {e}")
        return None, None

def get_option_price(client, symbol, side):
    """Fetches current LTP of option, using depth first then falling back to quotes."""
    try:
        if PAPER_MODE:
            # Paper mode placeholder price simulation
            return 100.0

        # Try depth
        depth_res = client.get_depth(exchange=OPTION_EXCHANGE, symbol=symbol)
        if isinstance(depth_res, dict) and depth_res.get("status") != "error":
            ltp = depth_res.get("data", {}).get("ltp", 0)
            depth = depth_res.get("data", {}).get("depth", {})
            buy_levels = depth.get("buy", [])
            sell_levels = depth.get("sell", [])
            
            bid = buy_levels[0].get("price", 0) if buy_levels else 0
            ask = sell_levels[0].get("price", 0) if sell_levels else 0
            
            price = bid if side == "BUY" else ask
            if price > 0:
                return float(price)
            if ltp > 0:
                return float(ltp)
                
        # Fallback to get_ltp
        ltp_res = client.get_ltp(exchange=OPTION_EXCHANGE, symbol=symbol)
        if isinstance(ltp_res, dict) and ltp_res.get("status") != "error":
            price = ltp_res.get("ltp", {}).get(OPTION_EXCHANGE, {}).get(symbol, {}).get("ltp", 0)
            if price > 0:
                return float(price)
                
    except Exception as e:
        print(f"[{datetime.now()}] Error getting quote for {symbol}: {e}")
    return None

# ─────────────────────────────────────────────────────────────────────────────
#  EXECUTION & ORDER ROUTING
# ─────────────────────────────────────────────────────────────────────────────

def place_limit_order(client, symbol, action, price, qty):
    """Sends LIMIT order request."""
    if PAPER_MODE:
        print(f"[PAPER MODE] Place LIMIT order: {action} {qty} {symbol} @ {price}")
        return {"status": "success", "orderid": f"paper_{int(time.time() * 1000)}"}
        
    try:
        res = client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=symbol,
            action=action,
            exchange=OPTION_EXCHANGE,
            price_type="LIMIT",
            product="MIS",
            quantity=qty,
            price=str(price)
        )
        return res
    except Exception as e:
        print(f"[{datetime.now()}] Exception placing limit order for {symbol}: {e}")
        return None

def unwind_order(client, symbol, action, qty):
    """Sends MARKET order to close a leg immediately (emergency fallback)."""
    if PAPER_MODE:
        print(f"[PAPER MODE] EMERGENCY UNWIND: Place MARKET order {action} {qty} {symbol}")
        return True
        
    try:
        res = client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=symbol,
            action=action,
            exchange=OPTION_EXCHANGE,
            price_type="MARKET",
            product="MIS",
            quantity=qty
        )
        print(f"[{datetime.now()}] Unwind order response: {res}")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] CRITICAL: Failed to unwind leg {symbol}: {e}")
        return False

def place_and_chase_order(client, symbol, action, qty):
    """Limit order chasing loop to minimize entry slippage."""
    price = get_option_price(client, symbol, action)
    if not price:
        print(f"[{datetime.now()}] Could not fetch price/LTP for {symbol}. Cannot place order.")
        return None

    max_slippage = BNF_CHASE_MAX_SLIPPAGE_POINTS
    step = BNF_CHASE_STEP_POINTS
    interval = BNF_CHASE_INTERVAL_SECS
    max_retries = BNF_CHASE_MAX_RETRIES

    current_price = price
    max_price = current_price + max_slippage if action == "BUY" else current_price - max_slippage
    if action == "SELL":
        max_price = max(max_price, 0.05)

    print(f"[{datetime.now()}] Starting chase for {action} {symbol}. Start={current_price:.2f}, Max={max_price:.2f}, Step={step:.2f}")

    res = place_limit_order(client, symbol, action, current_price, qty)
    if not res or res.get("status") == "error":
        print(f"[{datetime.now()}] Initial limit order rejected for {symbol}: {res}")
        return None

    order_id = res.get("orderid")
    if not order_id:
        print(f"[{datetime.now()}] Order placed but no orderid returned for {symbol}")
        return None

    if PAPER_MODE:
        return {"orderid": order_id, "status": "complete", "avg_price": current_price}

    retries = 0
    while retries < max_retries:
        time.sleep(interval)
        
        status_res = client.orderstatus(order_id=order_id, strategy=STRATEGY_NAME)
        if not status_res or status_res.get("status") == "error":
            print(f"[{datetime.now()}] Error checking status for ID {order_id}: {status_res}")
            retries += 1
            continue
            
        order_data = status_res.get("data", {})
        status = order_data.get("order_status", "").lower()
        
        if status in ("complete", "completed", "filled"):
            avg_price = float(order_data.get("price", current_price))
            print(f"[{datetime.now()}] Order {order_id} FILLED at avg price {avg_price:.2f}")
            return {"orderid": order_id, "status": "complete", "avg_price": avg_price}
            
        if status in ("rejected", "cancelled"):
            print(f"[{datetime.now()}] Order {order_id} failed/cancelled with status: {status}")
            return None

        # Adjust price and modify order
        if action == "BUY":
            current_price += step
            current_price = round(current_price, 2)
            if current_price > max_price:
                print(f"[{datetime.now()}] Max slippage breached for BUY {symbol} ({current_price:.2f} > {max_price:.2f}). Cancelling.")
                client.cancelorder(order_id=order_id, strategy=STRATEGY_NAME)
                return None
        else: # SELL
            current_price -= step
            current_price = round(current_price, 2)
            if current_price < max_price:
                print(f"[{datetime.now()}] Max slippage breached for SELL {symbol} ({current_price:.2f} < {max_price:.2f}). Cancelling.")
                client.cancelorder(order_id=order_id, strategy=STRATEGY_NAME)
                return None

        retries += 1
        print(f"[{datetime.now()}] Chasing {action} {symbol}: Modifying order {order_id} price to {current_price:.2f} (Retry {retries}/{max_retries})")
        
        try:
            mod_res = client.modifyorder(
                order_id=order_id,
                strategy=STRATEGY_NAME,
                symbol=symbol,
                action=action,
                exchange=OPTION_EXCHANGE,
                price_type="LIMIT",
                product="MIS",
                quantity=qty,
                price=str(current_price)
            )
            if mod_res and mod_res.get("status") == "error":
                print(f"[{datetime.now()}] Modify order rejected: {mod_res}. Cancelling.")
                client.cancelorder(order_id=order_id, strategy=STRATEGY_NAME)
                return None
        except Exception as e:
            print(f"[{datetime.now()}] Exception modifying order: {e}")

    print(f"[{datetime.now()}] Max retries hit for {action} {symbol}. Cancelling.")
    client.cancelorder(order_id=order_id, strategy=STRATEGY_NAME)
    return None

def resolve_spread_symbols(spot, signal_type, expiry_formatted):
    """Calculates strikes and formats Option symbols locally."""
    atm_strike = round(spot / STRIKE_INTERVAL) * STRIKE_INTERVAL
    if signal_type == "LONG": # Bull Call Spread
        otm_strike = atm_strike + SPREAD_WIDTH
        atm_sym = f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE"
        otm_sym = f"{UNDERLYING}{expiry_formatted}{int(otm_strike)}CE"
    else: # Bear Put Spread
        otm_strike = atm_strike - SPREAD_WIDTH
        atm_sym = f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}PE"
        otm_sym = f"{UNDERLYING}{expiry_formatted}{int(otm_strike)}PE"
    return atm_sym, otm_sym

def enter_bull_call_spread(client, spot, expiry_formatted, qty):
    """Long signal: Buy ATM CE, Sell OTM CE."""
    atm_sym, otm_sym = resolve_spread_symbols(spot, "LONG", expiry_formatted)
    print(f"[{datetime.now()}] Executing Bull Call Spread: BUY {atm_sym} / SELL {otm_sym}")
    
    buy_res = place_and_chase_order(client, atm_sym, "BUY", qty)
    if not buy_res:
        print(f"[{datetime.now()}] BUY leg {atm_sym} chase failed. Entry aborted.")
        return None
        
    sell_res = place_and_chase_order(client, otm_sym, "SELL", qty)
    if not sell_res:
        print(f"[{datetime.now()}] SELL leg {otm_sym} chase failed. EMERGENCY UNWIND of Buy leg {atm_sym}")
        unwind_order(client, atm_sym, "SELL", qty)
        return None
        
    entry_cost = buy_res["avg_price"] - sell_res["avg_price"]
    return {
        "type": "LONG",
        "atm_symbol": atm_sym,
        "otm_symbol": otm_sym,
        "atm_entry_price": buy_res["avg_price"],
        "otm_entry_price": sell_res["avg_price"],
        "entry_cost": entry_cost,
        "entry_time": time.time(),
        "qty": qty
    }

def enter_bear_put_spread(client, spot, expiry_formatted, qty):
    """Short signal: Buy ATM PE, Sell OTM PE."""
    atm_sym, otm_sym = resolve_spread_symbols(spot, "SHORT", expiry_formatted)
    print(f"[{datetime.now()}] Executing Bear Put Spread: BUY {atm_sym} / SELL {otm_sym}")
    
    buy_res = place_and_chase_order(client, atm_sym, "BUY", qty)
    if not buy_res:
        print(f"[{datetime.now()}] BUY leg {atm_sym} chase failed. Entry aborted.")
        return None
        
    sell_res = place_and_chase_order(client, otm_sym, "SELL", qty)
    if not sell_res:
        print(f"[{datetime.now()}] SELL leg {otm_sym} chase failed. EMERGENCY UNWIND of Buy leg {atm_sym}")
        unwind_order(client, atm_sym, "SELL", qty)
        return None
        
    entry_cost = buy_res["avg_price"] - sell_res["avg_price"]
    return {
        "type": "SHORT",
        "atm_symbol": atm_sym,
        "otm_symbol": otm_sym,
        "atm_entry_price": buy_res["avg_price"],
        "otm_entry_price": sell_res["avg_price"],
        "entry_cost": entry_cost,
        "entry_time": time.time(),
        "qty": qty
    }

def close_spread(client, active_spread):
    """Closes all legs of the active spread at market."""
    if not active_spread:
        return True
        
    atm_sym = active_spread["atm_symbol"]
    otm_sym = active_spread["otm_symbol"]
    qty = active_spread["qty"]
    
    print(f"[{datetime.now()}] CLOSING SPREAD: Sell ATM {atm_sym} / Buy OTM {otm_sym}")
    
    if PAPER_MODE:
        print(f"[PAPER MODE] Spread closed successfully.")
        return True
        
    try:
        # ATM leg: SELL to close
        res_atm = client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=atm_sym,
            action="SELL",
            exchange=OPTION_EXCHANGE,
            price_type="MARKET",
            product="MIS",
            quantity=qty
        )
        # OTM leg: BUY to close
        res_otm = client.placeorder(
            strategy=STRATEGY_NAME,
            symbol=otm_sym,
            action="BUY",
            exchange=OPTION_EXCHANGE,
            price_type="MARKET",
            product="MIS",
            quantity=qty
        )
        print(f"[{datetime.now()}] Close ATM response: {res_atm}")
        print(f"[{datetime.now()}] Close OTM response: {res_otm}")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] Error closing spread: {e}. Check positions manually!")
        return False

# ─────────────────────────────────────────────────────────────────────────────
#  RISK & TRAILING CHECKS
# ─────────────────────────────────────────────────────────────────────────────

def check_pnl_stop(client, active_spread):
    """Checks if the active spread has lost more than SPREAD_STOP_LOSS_PCT (15%)."""
    if not active_spread:
        return False
        
    atm_sym = active_spread["atm_symbol"]
    otm_sym = active_spread["otm_symbol"]
    entry_cost = active_spread["entry_cost"]
    
    atm_price = get_option_price(client, atm_sym, "BUY")
    otm_price = get_option_price(client, otm_sym, "SELL")
    
    if not atm_price or not otm_price:
        return False
        
    current_value = atm_price - otm_price
    loss = entry_cost - current_value
    max_loss = entry_cost * SPREAD_STOP_LOSS_PCT
    
    if loss >= max_loss:
        print(f"[{datetime.now()}] P&L STOP TRIGGERED! Entry Cost: {entry_cost:.2f}, Current Value: {current_value:.2f}, Loss: {loss:.2f} >= Max Loss: {max_loss:.2f}")
        return True
        
    return False

def compute_structural_stop(df, signal_type):
    """Computes the 5-candle spot swing high/low structural stop at entry."""
    lookback = STRUCTURAL_STOP_LOOKBACK
    
    # Identify if the last candle is in-progress
    last_is_inprogress = False
    if isinstance(df.index, pd.DatetimeIndex) and len(df) >= 2:
        now_ist = get_ist_now()
        current_minute_start = now_ist.replace(second=0, microsecond=0)
        last_candle_time = df.index[-1]
        if last_candle_time.timestamp() >= current_minute_start.timestamp():
            last_is_inprogress = True
            
    if last_is_inprogress:
        candles = df.iloc[-lookback - 1 : -1]
    else:
        candles = df.iloc[-lookback:]
    
    if signal_type == "LONG":
        stop = float(candles["low"].min())
        print(f"[{datetime.now()}] Computed Structural Stop (LONG): {stop:.2f}")
    else:
        stop = float(candles["high"].max())
        print(f"[{datetime.now()}] Computed Structural Stop (SHORT): {stop:.2f}")
    return stop

def check_structural_stop(df, active_spread, stop_level):
    """Checks if the spot index has breached the structural stop on candle close."""
    if not active_spread or not stop_level:
        return False
        
    last_completed = get_last_completed_candle(df)
    last_close = float(last_completed["close"])
    spread_type = active_spread["type"]
    
    if spread_type == "LONG":
        if last_close < stop_level:
            print(f"[{datetime.now()}] STRUCTURAL STOP TRIGGERED! Spot Close {last_close:.2f} < Stop Level {stop_level:.2f}")
            return True
    else: # SHORT
        if last_close > stop_level:
            print(f"[{datetime.now()}] STRUCTURAL STOP TRIGGERED! Spot Close {last_close:.2f} > Stop Level {stop_level:.2f}")
            return True
            
    return False

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN STRATEGY ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"[{datetime.now()}] Initialize Bot 1 (Hull BBI + DTC Ribbon Options Spread)")
    print(f"[{datetime.now()}] Parameters: Underlying={UNDERLYING}, Lot Size={LOT_SIZE}, Spread Width={SPREAD_WIDTH}")
    
    api_key = os.getenv("OPENALGO_API_KEY")
    host = os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
    ws_url = os.getenv("WEBSOCKET_URL") or (
        f"ws://{os.getenv('WEBSOCKET_HOST', '127.0.0.1')}:{os.getenv('WEBSOCKET_PORT', '8765')}"
    )
    
    if not api_key:
        print("Error: OPENALGO_API_KEY environment variable not set")
        sys.exit(1)
        
    client = api(api_key=api_key, host=host, ws_url=ws_url)
    
    hull_bbi = HullBBI(length=HMA_LENGTH)
    dtc_ribbon = DTCRibbon(lengths=EMA_LENGTHS)
    
    # Load recovered state if any
    active_spread, stop_level = load_state()
    current_position = active_spread["type"] if active_spread else None
    if active_spread:
        print(f"[{datetime.now()}] State Recovered: Active {current_position} spread on {active_spread['atm_symbol']} / {active_spread['otm_symbol']}")
        # Re-subscribe to live option ticks
        client.connect()
        client.subscribe_ltp([
            {"exchange": OPTION_EXCHANGE, "symbol": active_spread["atm_symbol"]},
            {"exchange": OPTION_EXCHANGE, "symbol": active_spread["otm_symbol"]}
        ])
    else:
        print(f"[{datetime.now()}] State Clean: Flat")
        
    last_processed_timestamp = None
    
    print(f"[{datetime.now()}] Starting loop...")
    while True:
        try:
            in_entry_window, past_square_off = check_time_windows()
            
            # EOD check
            if past_square_off:
                if active_spread:
                    print(f"[{datetime.now()}] HARD SQUARE-OFF time reached. Flattening.")
                    close_spread(client, active_spread)
                    client.unsubscribe_ltp([
                        {"exchange": OPTION_EXCHANGE, "symbol": active_spread["atm_symbol"]},
                        {"exchange": OPTION_EXCHANGE, "symbol": active_spread["otm_symbol"]}
                    ])
                    active_spread = None
                    stop_level = None
                    current_position = None
                    clear_state()
                time.sleep(10)
                continue

            # Risk check: 15% P&L Stop (evaluated continuously)
            if active_spread:
                if check_pnl_stop(client, active_spread):
                    close_spread(client, active_spread)
                    client.unsubscribe_ltp([
                        {"exchange": OPTION_EXCHANGE, "symbol": active_spread["atm_symbol"]},
                        {"exchange": OPTION_EXCHANGE, "symbol": active_spread["otm_symbol"]}
                    ])
                    active_spread = None
                    stop_level = None
                    current_position = None
                    clear_state()
                    time.sleep(15) # Cooldown
                    continue
            
            # Fetch history and calculate indicators
            df = get_history(client)
            if df is None or df.empty:
                time.sleep(5)
                continue
                
            df = hull_bbi.compute(df)
            df = dtc_ribbon.compute(df)
            
            # Evaluate new completed candle
            last_completed = get_last_completed_candle(df)
            candle_time = last_completed.name
            
            if last_processed_timestamp != candle_time:
                print(f"[{datetime.now()}] Completed candle at {candle_time} | Close: {last_completed['close']:.2f}")
                
                # Risk check: Spot structural stop (evaluated on candle close)
                if active_spread:
                    if check_structural_stop(df, active_spread, stop_level):
                        close_spread(client, active_spread)
                        client.unsubscribe_ltp([
                            {"exchange": OPTION_EXCHANGE, "symbol": active_spread["atm_symbol"]},
                            {"exchange": OPTION_EXCHANGE, "symbol": active_spread["otm_symbol"]}
                        ])
                        active_spread = None
                        stop_level = None
                        current_position = None
                        clear_state()
                        last_processed_timestamp = candle_time
                        continue
                
                # Check entry/exit signals
                signal = check_signals(df, current_position)
                
                if signal:
                    spot_price = float(last_completed["close"])
                    
                    if signal in ("EXIT_LONG", "EXIT_SHORT"):
                        print(f"[{datetime.now()}] Signal exit: {signal} at spot {spot_price:.2f}")
                        close_spread(client, active_spread)
                        client.unsubscribe_ltp([
                            {"exchange": OPTION_EXCHANGE, "symbol": active_spread["atm_symbol"]},
                            {"exchange": OPTION_EXCHANGE, "symbol": active_spread["otm_symbol"]}
                        ])
                        active_spread = None
                        stop_level = None
                        current_position = None
                        clear_state()
                        
                    elif signal in ("LONG", "SHORT") and in_entry_window:
                        print(f"[{datetime.now()}] Signal entry: {signal} at spot {spot_price:.2f}")
                        expiry_formatted, expiry_raw = get_nearest_expiry(client)
                        if not expiry_formatted:
                            print(f"[{datetime.now()}] No valid option expiry. Suppression entry.")
                        else:
                            if signal == "LONG":
                                active_spread = enter_bull_call_spread(
                                    client, spot_price, expiry_formatted, LOT_SIZE * LOT_MULTIPLIER
                                )
                            else: # SHORT
                                active_spread = enter_bear_put_spread(
                                    client, spot_price, expiry_formatted, LOT_SIZE * LOT_MULTIPLIER
                                )
                                
                            if active_spread:
                                stop_level = compute_structural_stop(df, signal)
                                current_position = signal
                                save_state(active_spread, stop_level)
                                
                                # Subscribe to option prices
                                client.connect()
                                client.subscribe_ltp([
                                    {"exchange": OPTION_EXCHANGE, "symbol": active_spread["atm_symbol"]},
                                    {"exchange": OPTION_EXCHANGE, "symbol": active_spread["otm_symbol"]}
                                ])
                                
                last_processed_timestamp = candle_time
                
        except Exception as e:
            print(f"[{datetime.now()}] Exception in strategy loop: {e}")
            traceback.print_exc()
            
        time.sleep(2.5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutdown via Ctrl+C")
