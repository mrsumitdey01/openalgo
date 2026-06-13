import sys
import os
import json
sys.path.append(os.getcwd())

from services.backtest_mcx_service import calculate_statutory_charges

# Let's simulate 1 Lot of Crude Oil (100 units) options spread
# Underlying spot price = 6000
spot_price = 6000
unit_size = 100
qty = 1 * unit_size

# Synthetic spread premium is 0.5% of spot = 30
entry_spread = spot_price * 0.005
entry_value = entry_spread * qty  # 30 * 100 = 3000

print(f"--- Option Spread Execution (2 Legs) ---")
print(f"Spot: {spot_price}, Spread Premium Paid: {entry_spread}")
print(f"Net Premium Trade Value: {entry_value}")

# In an options spread, legs = 2
entry_fee, breakdown = calculate_statutory_charges(
    profile="mcx_options",
    value=entry_value,
    qty=qty,
    side="BUY",
    legs=2
)

print(f"\nEntry Charges Breakdown (Legs=2):")
print(json.dumps(breakdown, indent=2))
