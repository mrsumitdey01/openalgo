import time
from datetime import datetime

# Mocks
UNDERLYING = "BANKNIFTY"
STRIKE_INTERVAL = 100
SPREAD_WIDTH = 500

def place_and_chase_order(client, symbol, action, qty):
    print(f"[MOCK] place_and_chase_order: {action} {qty} {symbol}")
    return {"avg_price": 500.0 if "CE" in symbol or "PE" in symbol else 50000.0, "symbol": symbol, "qty": qty}

def unwind_order(client, symbol, action, qty):
    print(f"[MOCK] unwind_order: {action} {qty} {symbol}")
    return True

def resolve_future_symbol(expiry_formatted):
    return f"{UNDERLYING}{expiry_formatted}FUT"

def resolve_symbols(spot, signal_type, expiry_formatted, mode):
    atm_strike = round(spot / STRIKE_INTERVAL) * STRIKE_INTERVAL
    
    if mode == "options_buying":
        if signal_type == "LONG":
            return f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE", None
        else:
            return f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}PE", None
            
    elif mode == "options_selling":
        if signal_type == "LONG":
            return f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}PE", None
        else:
            return f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE", None
            
    else: # options_spread
        if signal_type == "LONG":
            otm_strike = atm_strike + SPREAD_WIDTH
            atm_sym = f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE"
            otm_sym = f"{UNDERLYING}{expiry_formatted}{int(otm_strike)}CE"
        else:
            otm_strike = atm_strike - SPREAD_WIDTH
            atm_sym = f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}PE"
            otm_sym = f"{UNDERLYING}{expiry_formatted}{int(otm_strike)}PE"
        return atm_sym, otm_sym

def execute_trade(client, spot, signal_type, expiry_formatted, qty, mode):
    """Master execution router based on profile."""
    if mode == "futures":
        sym = resolve_future_symbol(expiry_formatted)
        action = "BUY" if signal_type == "LONG" else "SELL"
        print(f"[{datetime.now()}] Executing Future: {action} {sym}")
        
        # We can limit chase futures or market order them. We'll use limit chase for consistency
        res = place_and_chase_order(client, sym, action, qty)
        if res:
            return {
                "profile": mode,
                "type": signal_type,
                "symbol": sym,
                "action": action,
                "entry_price": res["avg_price"],
                "entry_cost": res["avg_price"], # Just raw entry price
                "entry_time": time.time(),
                "qty": qty
            }
        return None
        
    elif mode in ["options_buying", "options_selling"]:
        sym, _ = resolve_symbols(spot, signal_type, expiry_formatted, mode)
        action = "BUY" if mode == "options_buying" else "SELL"
        print(f"[{datetime.now()}] Executing Naked Option ({mode}): {action} {sym}")
        
        res = place_and_chase_order(client, sym, action, qty)
        if res:
            return {
                "profile": mode,
                "type": signal_type,
                "symbol": sym,
                "action": action,
                "entry_price": res["avg_price"],
                "entry_cost": res["avg_price"], # Single premium
                "entry_time": time.time(),
                "qty": qty
            }
        return None
        
    else: # options_spread
        atm_sym, otm_sym = resolve_symbols(spot, signal_type, expiry_formatted, mode)
        print(f"[{datetime.now()}] Executing Spread: BUY {atm_sym} / SELL {otm_sym}")
        
        buy_res = place_and_chase_order(client, atm_sym, "BUY", qty)
        if not buy_res:
            return None
            
        sell_res = place_and_chase_order(client, otm_sym, "SELL", qty)
        if not sell_res:
            unwind_order(client, atm_sym, "SELL", qty)
            return None
            
        entry_cost = buy_res["avg_price"] - sell_res["avg_price"]
        return {
            "profile": mode,
            "type": signal_type,
            "atm_symbol": atm_sym,
            "otm_symbol": otm_sym,
            "atm_entry_price": buy_res["avg_price"],
            "otm_entry_price": sell_res["avg_price"],
            "entry_cost": entry_cost,
            "entry_time": time.time(),
            "qty": qty
        }


# MOCK client
class MockClient:
    def placeorder(self, strategy, symbol, action, exchange, price_type, product, quantity):
        print(f"[MOCK client] EXIT MARKET ORDER: {action} {quantity} {symbol}")

def close_position(client, active_spread):
    if not active_spread:
        return True
    
    # We will pretend PAPER_MODE is false to test logic
    profile = active_spread.get("profile", "options_spread")
    qty = active_spread["qty"]
    
    try:
        if profile == "options_spread":
            atm_sym = active_spread["atm_symbol"]
            otm_sym = active_spread["otm_symbol"]
            print(f"[{datetime.now()}] CLOSING SPREAD: Sell ATM {atm_sym} / Buy OTM {otm_sym}")
            client.placeorder(strategy="TEST", symbol=atm_sym, action="SELL", exchange="NFO", price_type="MARKET", product="MIS", quantity=qty)
            client.placeorder(strategy="TEST", symbol=otm_sym, action="BUY", exchange="NFO", price_type="MARKET", product="MIS", quantity=qty)
            
        else: # futures, options_buying, options_selling
            sym = active_spread["symbol"]
            entry_action = active_spread["action"]
            exit_action = "SELL" if entry_action == "BUY" else "BUY"
            exchange_used = "NFO" 
            print(f"[{datetime.now()}] CLOSING {profile.upper()}: {exit_action} {sym}")
            client.placeorder(strategy="TEST", symbol=sym, action=exit_action, exchange=exchange_used, price_type="MARKET", product="MIS", quantity=qty)
            
        print(f"[{datetime.now()}] Position closed at market.")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] Error closing position: {e}")
        return False

# Tests
client = MockClient()

print("--- Testing Futures LONG ---")
state = execute_trade(client, 50123, "LONG", "24JUN", 15, "futures")
print(state)
close_position(client, state)

print("\n--- Testing Futures SHORT ---")
state = execute_trade(client, 50123, "SHORT", "24JUN", 15, "futures")
print(state)
close_position(client, state)

print("\n--- Testing Options Buying LONG ---")
state = execute_trade(client, 50123, "LONG", "24JUN", 15, "options_buying")
print(state)
close_position(client, state)

print("\n--- Testing Options Buying SHORT ---")
state = execute_trade(client, 50123, "SHORT", "24JUN", 15, "options_buying")
print(state)
close_position(client, state)

print("\n--- Testing Options Selling LONG ---")
state = execute_trade(client, 50123, "LONG", "24JUN", 15, "options_selling")
print(state)
close_position(client, state)

print("\n--- Testing Options Selling SHORT ---")
state = execute_trade(client, 50123, "SHORT", "24JUN", 15, "options_selling")
print(state)
close_position(client, state)

print("\n--- Testing Options Spread LONG ---")
state = execute_trade(client, 50123, "LONG", "24JUN", 15, "options_spread")
print(state)
close_position(client, state)

print("\n--- Testing Options Spread SHORT ---")
state = execute_trade(client, 50123, "SHORT", "24JUN", 15, "options_spread")
print(state)
close_position(client, state)
