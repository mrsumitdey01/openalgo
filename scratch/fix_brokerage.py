import sys
import os

files = [
    'services/backtest_service.py',
    'services/backtest_mcx_service.py'
]

for filepath in files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Update the function signature and brokerage calculation
    old_func = "def calculate_statutory_charges(profile, value, qty, side):"
    new_func = "def calculate_statutory_charges(profile, value, qty, side, legs=1):\n    # For spreads, gross turnover is much larger than net spread premium.\n    # We approximate gross premium turnover as 5x the net spread premium for realistic STT/Txn fees.\n    if legs > 1:\n        value = value * 5.0"
    content = content.replace(old_func, new_func)

    # Replace brokerage = 20.0 with brokerage = 20.0 * legs
    content = content.replace('brokerage = 20.0\n', 'brokerage = 20.0 * legs\n')

    # 2. Update the calls in the code to pass legs
    # There are multiple places where calculate_statutory_charges is called.
    # We will replace them with a dynamic `legs` parameter based on execution_mode.
    
    # First, let's inject a legs variable right after execution_mode is determined or just before calculate_statutory_charges
    # It's easier to dynamically replace the calls.
    
    old_call = "calculate_statutory_charges(charges_profile, exit_value, qty_units, exit_side)"
    new_call = "calculate_statutory_charges(charges_profile, exit_value, qty_units, exit_side, legs=2 if 'spread' in execution_mode else 1)"
    content = content.replace(old_call, new_call)
    
    old_call2 = "calculate_statutory_charges(charges_profile, exit_value, qty, exit_side)"
    new_call2 = "calculate_statutory_charges(charges_profile, exit_value, qty, exit_side, legs=2 if 'spread' in execution_mode else 1)"
    content = content.replace(old_call2, new_call2)
    
    old_call3 = "calculate_statutory_charges(charges_profile, entry_value, total_qty_units, entry_side)"
    new_call3 = "calculate_statutory_charges(charges_profile, entry_value, total_qty_units, entry_side, legs=2 if 'spread' in execution_mode else 1)"
    content = content.replace(old_call3, new_call3)
    
    old_call4 = "calculate_statutory_charges(charges_profile, entry_value, qty, entry_side)"
    new_call4 = "calculate_statutory_charges(charges_profile, entry_value, qty, entry_side, legs=2 if 'spread' in execution_mode else 1)"
    content = content.replace(old_call4, new_call4)

    # Some variables might be slightly different in bot 1 vs bot 2
    old_call5 = "calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side)"
    new_call5 = "calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side, legs=2 if 'spread' in execution_mode else 1)"
    content = content.replace(old_call5, new_call5)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

print("Brokerage and statutory charges fixed for multi-leg execution.")
