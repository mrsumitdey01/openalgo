import os

file_path = r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\strategies\scripts\bot1_hull_dtc_ribbon.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

target_block = '''def resolve_spread_symbols(spot, signal_type, expiry_formatted):'''

if target_block not in content:
    print('Target block not found!')
    exit(1)

# Find the end of the close_spread block
end_str = '''    print(f"[{datetime.now()}] Spread fully closed.")'''
if end_str not in content:
    print('End string not found!')
    exit(1)

start_index = content.find(target_block)
end_index = content.find(end_str) + len(end_str)

replacement = '''def resolve_future_symbol(expiry_formatted):
    """Calculates Futures ticker format."""
    return f"{UNDERLYING}{expiry_formatted}FUT"

def resolve_option_symbol(spot, signal_type, expiry_formatted, mode):
    """Calculates strikes and formats Option symbols locally."""
    atm_strike = round(spot / STRIKE_INTERVAL) * STRIKE_INTERVAL
    
    if mode == "options_buying":
        if signal_type == "LONG":
            return f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE"
        else:
            return f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}PE"
    elif mode == "options_selling":
        if signal_type == "LONG":
            return f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}PE"
        else:
            return f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE"
    else: # Spreads
        if signal_type == "LONG": # Bull Call Spread
            otm_strike = atm_strike + SPREAD_WIDTH
            atm_sym = f"{UNDERLYING}{expiry_formatted}{int(atm_strike)}CE"
            otm_sym = f"{UNDERLYING}{expiry_formatted}{int(otm_strike)}CE"
        else: # Bear Put Spread
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
        res = place_and_chase_order(client, sym, action, qty)
        if res:
            return {"type": "FUTURE", "leg1": res, "action": action}
        return None
        
    elif mode in ["options_buying", "options_selling"]:
        sym = resolve_option_symbol(spot, signal_type, expiry_formatted, mode)
        action = "BUY" if mode == "options_buying" else "SELL"
        print(f"[{datetime.now()}] Executing Naked Option {mode}: {action} {sym}")
        
        res = place_and_chase_order(client, sym, action, qty)
        if res:
            return {"type": "NAKED_OPTION", "leg1": res, "action": action}
        return None
        
    else: # options_spread
        atm_sym, otm_sym = resolve_option_symbol(spot, signal_type, expiry_formatted, mode)
        print(f"[{datetime.now()}] Executing Spread: BUY {atm_sym} / SELL {otm_sym}")
        buy_res = place_and_chase_order(client, atm_sym, "BUY", qty)
        if not buy_res: return None
        sell_res = place_and_chase_order(client, otm_sym, "SELL", qty)
        if not sell_res:
            print(f"[{datetime.now()}] Spread leg 2 failed! WARNING: Naked position {atm_sym}")
            return None
        return {"type": "SPREAD", "leg1": buy_res, "leg2": sell_res}

def close_position(client, active_position):
    """Universal closer for any active position."""
    leg1 = active_position["leg1"]
    
    if active_position["type"] == "SPREAD":
        leg2 = active_position["leg2"]
        print(f"[{datetime.now()}] Closing spread leg1: {leg1['symbol']}")
        unwind_order(client, leg1['symbol'], "SELL", leg1['qty'])
        print(f"[{datetime.now()}] Closing spread leg2: {leg2['symbol']}")
        unwind_order(client, leg2['symbol'], "BUY", leg2['qty'])
        print(f"[{datetime.now()}] Spread fully closed.")
    else:
        # Future or Naked Option
        action = "SELL" if active_position["action"] == "BUY" else "BUY"
        print(f"[{datetime.now()}] Closing position: {action} {leg1['symbol']}")
        unwind_order(client, leg1['symbol'], action, leg1['qty'])
        print(f"[{datetime.now()}] Position fully closed.")'''

new_content = content[:start_index] + replacement + content[end_index:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Successfully patched execution functions!')
