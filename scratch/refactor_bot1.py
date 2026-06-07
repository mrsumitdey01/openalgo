import os
import re

file_path = r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\strategies\scripts\bot1_hull_dtc_ribbon.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update resolve_spread_symbols -> resolve_symbols
target_resolve = '''def resolve_spread_symbols(spot, signal_type, expiry_formatted):
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
    return atm_sym, otm_sym'''

replacement_resolve = '''def resolve_future_symbol(expiry_formatted):
    # Depending on broker, expiry format might differ, but generic format is standard
    # e.g., BANKNIFTY26JUNFUT
    return f"{UNDERLYING}{expiry_formatted}FUT"

def resolve_symbols(spot, signal_type, expiry_formatted, mode):
    """Calculates strikes and formats Option symbols based on execution mode."""
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
        return atm_sym, otm_sym'''

content = content.replace(target_resolve, replacement_resolve)

# 2. Update Entry Blocks
target_entry_blocks = '''def enter_bull_call_spread(client, spot, expiry_formatted, qty):
    """Long signal: Buy ATM CE, Sell OTM CE."""
    atm_sym, otm_sym = resolve_spread_symbols(spot, "LONG", expiry_formatted)
    print(f"[{datetime.now()}] Executing Bull Call Spread: BUY {atm_sym} / SELL {otm_sym}")
    
    buy_res = place_and_chase_order(client, atm_sym, "BUY", qty)
    if not buy_res: return None
    
    sell_res = place_and_chase_order(client, otm_sym, "SELL", qty)
    if not sell_res:
        print(f"[{datetime.now()}] Spread leg 2 failed! WARNING: Naked position {atm_sym}")
        # Could implement auto-unwind here
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
    if not buy_res: return None
    
    sell_res = place_and_chase_order(client, otm_sym, "SELL", qty)
    if not sell_res:
        print(f"[{datetime.now()}] Spread leg 2 failed! WARNING: Naked position {atm_sym}")
        # Could implement auto-unwind here
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
    }'''

# Replace it with generic execute_trade
replacement_entry = '''def execute_trade(client, spot, signal_type, expiry_formatted, qty, mode):
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
            print(f"[{datetime.now()}] BUY leg {atm_sym} chase failed. Entry aborted.")
            return None
            
        sell_res = place_and_chase_order(client, otm_sym, "SELL", qty)
        if not sell_res:
            print(f"[{datetime.now()}] SELL leg {otm_sym} chase failed. EMERGENCY UNWIND of Buy leg {atm_sym}")
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
        }'''

if target_entry_blocks in content:
    content = content.replace(target_entry_blocks, replacement_entry)
else:
    print("Entry blocks not found perfectly!")
    # Use regex
    content = re.sub(r'def enter_bull_call_spread.*?return {\n.*?qty\n    }', replacement_entry, content, flags=re.DOTALL)


# 3. Update close_spread -> close_position
target_close = '''def close_spread(client, active_spread):
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
        print(f"[{datetime.now()}] Spread legs closed at market.")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] Error closing spread: {e}")
        return False'''

replacement_close = '''def close_position(client, active_spread):
    """Closes any active position based on its profile."""
    if not active_spread:
        return True
        
    profile = active_spread.get("profile", "options_spread")
    qty = active_spread["qty"]
    
    if PAPER_MODE:
        print(f"[PAPER MODE] {profile} closed successfully.")
        return True
        
    try:
        if profile == "options_spread":
            atm_sym = active_spread["atm_symbol"]
            otm_sym = active_spread["otm_symbol"]
            print(f"[{datetime.now()}] CLOSING SPREAD: Sell ATM {atm_sym} / Buy OTM {otm_sym}")
            # Use MARKET orders to prevent Broken Wings
            client.placeorder(strategy=STRATEGY_NAME, symbol=atm_sym, action="SELL", exchange=OPTION_EXCHANGE, price_type="MARKET", product="MIS", quantity=qty)
            client.placeorder(strategy=STRATEGY_NAME, symbol=otm_sym, action="BUY", exchange=OPTION_EXCHANGE, price_type="MARKET", product="MIS", quantity=qty)
            
        else: # futures, options_buying, options_selling
            sym = active_spread["symbol"]
            entry_action = active_spread["action"]
            exit_action = "SELL" if entry_action == "BUY" else "BUY"
            exchange_used = OPTION_EXCHANGE # Fyers handles futures in NFO usually
            print(f"[{datetime.now()}] CLOSING {profile.upper()}: {exit_action} {sym}")
            
            client.placeorder(strategy=STRATEGY_NAME, symbol=sym, action=exit_action, exchange=exchange_used, price_type="MARKET", product="MIS", quantity=qty)
            
        print(f"[{datetime.now()}] Position closed at market.")
        return True
    except Exception as e:
        print(f"[{datetime.now()}] Error closing position: {e}")
        return False'''

if target_close in content:
    content = content.replace(target_close, replacement_close)
else:
    print("Close block not found exactly. Using regex.")
    content = re.sub(r'def close_spread.*?return False', replacement_close, content, flags=re.DOTALL)


# 4. Refactor check_pnl_stop
target_pnl = '''def check_pnl_stop(client, active_spread):
    """Evaluates if the spread's current net value has breached the max loss %."""
    try:
        res = client.quotes(exchange=OPTION_EXCHANGE, symbol=f"{active_spread['atm_symbol']},{active_spread['otm_symbol']}")
        if res and res.get("s") == "ok":
            quotes = {q["n"]: q["v"] for q in res["d"]}
            atm_bid = quotes.get(f"{OPTION_EXCHANGE}:{active_spread['atm_symbol']}", {}).get("bid")
            otm_ask = quotes.get(f"{OPTION_EXCHANGE}:{active_spread['otm_symbol']}", {}).get("ask")
            
            if atm_bid and otm_ask:
                current_val = atm_bid - otm_ask
                loss_pct = (active_spread["entry_cost"] - current_val) / active_spread["entry_cost"]
                if loss_pct >= SPREAD_STOP_LOSS_PCT:
                    print(f"[{datetime.now()}] 15% STOP LOSS BREACHED! Entry: {active_spread['entry_cost']:.2f}, Current: {current_val:.2f} ({loss_pct*100:.1f}%)")
                    return True
        return False
    except Exception as e:
        print(f"[{datetime.now()}] Error checking PnL stop: {e}")
        return False'''

replacement_pnl = '''def check_pnl_stop(client, active_spread):
    """Evaluates if the current position value has breached the max loss limit."""
    try:
        profile = active_spread.get("profile", "options_spread")
        
        if profile == "options_spread":
            res = client.quotes(exchange=OPTION_EXCHANGE, symbol=f"{active_spread['atm_symbol']},{active_spread['otm_symbol']}")
            if res and res.get("s") == "ok":
                quotes = {q["n"]: q["v"] for q in res["d"]}
                atm_bid = quotes.get(f"{OPTION_EXCHANGE}:{active_spread['atm_symbol']}", {}).get("bid")
                otm_ask = quotes.get(f"{OPTION_EXCHANGE}:{active_spread['otm_symbol']}", {}).get("ask")
                
                if atm_bid and otm_ask:
                    current_val = atm_bid - otm_ask
                    loss_pct = (active_spread["entry_cost"] - current_val) / active_spread["entry_cost"]
                    if loss_pct >= SPREAD_STOP_LOSS_PCT:
                        print(f"[{datetime.now()}] {SPREAD_STOP_LOSS_PCT*100}% STOP LOSS BREACHED! Entry: {active_spread['entry_cost']:.2f}, Current: {current_val:.2f}")
                        return True
                        
        elif profile in ["options_buying", "options_selling", "futures"]:
            sym = active_spread["symbol"]
            res = client.quotes(exchange=OPTION_EXCHANGE, symbol=sym)
            if res and res.get("s") == "ok" and res["d"]:
                lp = res["d"][0]["v"]["lp"]
                entry = active_spread["entry_cost"]
                
                # If Buying Options: Stop if price drops by X%
                if profile == "options_buying":
                    loss_pct = (entry - lp) / entry
                    # Naked options decay faster, maybe use a 25% stop instead of 15% to avoid whipsaws, 
                    # but we'll use SPREAD_STOP_LOSS_PCT to be consistent with config.
                    if loss_pct >= SPREAD_STOP_LOSS_PCT:
                        print(f"[{datetime.now()}] BUYING STOP LOSS BREACHED! Entry: {entry:.2f}, LP: {lp:.2f}")
                        return True
                        
                # If Selling Options: Stop if price surges by X%
                elif profile == "options_selling":
                    loss_pct = (lp - entry) / entry
                    if loss_pct >= SPREAD_STOP_LOSS_PCT:
                        print(f"[{datetime.now()}] SELLING STOP LOSS BREACHED! Entry: {entry:.2f}, LP: {lp:.2f}")
                        return True
                        
                # If Futures: Use points-based stop (e.g. 150 points) because 15% of 50000 is 7500!
                elif profile == "futures":
                    action = active_spread["action"]
                    point_loss = (entry - lp) if action == "BUY" else (lp - entry)
                    if point_loss >= 150.0:  # 150 points stop loss for futures
                        print(f"[{datetime.now()}] FUTURES STOP LOSS BREACHED! Entry: {entry:.2f}, LP: {lp:.2f}, Loss: {point_loss:.2f}pts")
                        return True

        return False
    except Exception as e:
        print(f"[{datetime.now()}] Error checking PnL stop: {e}")
        return False'''

if target_pnl in content:
    content = content.replace(target_pnl, replacement_pnl)
else:
    print("PnL block not found exactly. Regex...")
    content = re.sub(r'def check_pnl_stop.*?return False', replacement_pnl, content, flags=re.DOTALL)


# 5. Finally, update the Main Loop
# Find: `if signal == "LONG":` down to `active_spread = enter_bear_put_spread(...)`
# Replace with `active_spread = execute_trade(...)`

target_main = '''                    if signal == "LONG":
                        print(f"[{datetime.now()}] LONG SIGNAL DETECTED.")
                        active_spread = enter_bull_call_spread(
                            client, spot, expiry_formatted, qty
                        )
                    else: # SHORT
                        print(f"[{datetime.now()}] SHORT SIGNAL DETECTED.")
                        active_spread = enter_bear_put_spread(
                            client, spot, expiry_formatted, qty
                        )'''

replacement_main = '''                    print(f"[{datetime.now()}] {signal} SIGNAL DETECTED. Mode: {EXECUTION_MODE}")
                    active_spread = execute_trade(client, spot, signal, expiry_formatted, qty, EXECUTION_MODE)'''

content = content.replace(target_main, replacement_main)

# Replace `close_spread(client, active_spread)` with `close_position(client, active_spread)`
content = content.replace('close_spread(client, active_spread)', 'close_position(client, active_spread)')

# Overwrite file
with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patching complete!")
