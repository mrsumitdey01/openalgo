import sys
import re

path = 'services/backtest_mcx_service.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# We need to target the run_bot2_mcx_backtest specifically
parts = content.split('def run_bot2_mcx_backtest(params: dict) -> tuple[bool, dict, int]:')
if len(parts) == 2:
    top = parts[0]
    bot2 = 'def run_bot2_mcx_backtest(params: dict) -> tuple[bool, dict, int]:' + parts[1]

    # Change the PnL stop logic
    old_pnl_stop_logic = """                # Evaluate PnL Stop
                pnl_stop_breached = False
                if execution_mode == "futures":
                    if open_position["type"] == "LONG" and spot_diff <= -150.0:
                        pnl_stop_breached = True
                    elif open_position["type"] == "SHORT" and spot_diff >= 150.0:
                        pnl_stop_breached = True
                else:
                    entry_value = open_position["entry_spread"] * qty_units
                    if entry_value > 0 and temp_gross_pnl <= -0.15 * entry_value:
                        pnl_stop_breached = True"""
                        
    new_pnl_stop_logic = """                # Dynamic Smart Stops for Bot 2 (High Win Rate & Low DD)
                pnl_stop_breached = False
                exit_reason_str = ""
                
                # Trailing stop mechanics
                max_favorable_excursion = open_position.get("mfe", 0.0)
                if open_position["type"] == "LONG":
                    if spot_diff > max_favorable_excursion:
                        open_position["mfe"] = spot_diff
                else:
                    if -spot_diff > max_favorable_excursion:
                        open_position["mfe"] = -spot_diff
                        
                mfe = open_position.get("mfe", 0.0)
                current_excursion = spot_diff if open_position["type"] == "LONG" else -spot_diff
                
                # 30 point trailing stop after 60 points in profit
                if mfe >= 60.0:
                    if current_excursion <= mfe - 30.0:
                        pnl_stop_breached = True
                        exit_reason_str = "Trailing Stop"
                # Hard stop at 45 points
                elif current_excursion <= -45.0:
                    pnl_stop_breached = True
                    exit_reason_str = "Hard Stop (-45 pts)"
                # Take profit at 150 points
                elif current_excursion >= 150.0:
                    pnl_stop_breached = True
                    exit_reason_str = "Take Profit (150 pts)"
"""

    bot2 = bot2.replace(old_pnl_stop_logic, new_pnl_stop_logic)
    
    # Also update the exit reason string in the subsequent block
    bot2 = bot2.replace('exit_reason = "15% PnL Stop"', 'exit_reason = exit_reason_str')
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(top + bot2)
    print("Patched Bot 2 Trailing Stops")
else:
    print("Could not find run_bot2_mcx_backtest")
