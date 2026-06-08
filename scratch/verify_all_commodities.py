"""
Full MCX commodity verification.
Tests all symbols in the MCX_UNIT_SIZES table using realistic market prices.
Verifies charge math is internally consistent and PnL values are sensible.
"""
import sys
sys.path.append('.')
from services.backtest_mcx_service import calculate_statutory_charges

# ── MCX contract specs: unit_size and typical spot prices ──────────────────
# unit_size = how many physical units in 1 lot
# price     = typical spot index price (what our DB stores)
# price_quote = what 1 "unit" represents (for understanding)
CONTRACTS = {
    # Symbol          unit_size  typical_price  description
    "CRUDEOIL":   (100,   6000,    "100 barrels/lot, ₹/barrel   [Zerodha verified]"),
    "CRUDEOILM":  (10,    6000,    "10 barrels/lot (mini), ₹/barrel"),
    "NATURALGAS": (1250,  250,     "1250 mmBtu/lot, ₹/mmBtu"),
    "GOLDM":      (10,    100000,  "100g lot / 10g unit = 10 units  [Zerodha verified]"),
    "GOLD":       (100,   100000,  "1kg lot  / 10g unit = 100 units [Zerodha verified]"),
    "SILVER":     (30,    90000,   "30 kg/lot, price ₹/kg"),
    "SILVERM":    (5,     90000,   "5 kg/lot (mini), ₹/kg"),
    "COPPER":     (2500,  800,     "2500 kg/lot, ₹/kg"),
    "ZINC":       (5000,  250,     "5000 kg/lot, ₹/kg"),
    "LEAD":       (5000,  185,     "5000 kg/lot, ₹/kg"),
    "ALUMINIUM":  (5000,  220,     "5000 kg/lot, ₹/kg"),
    "NICKEL":     (1500,  1400,    "1500 kg/lot, ₹/kg"),
}

print("\n" + "="*90)
print(f"  {'SYMBOL':<14} {'UNIT':>5}  {'SPOT':>8}  {'NOTIONAL':>12}  {'GROSS PnL':>10}  {'CHARGES':>10}  {'NET PnL':>10}  SANE?")
print("="*90)

all_pass = True
for symbol, (unit_size, price, desc) in CONTRACTS.items():
    # Simulate: 1% profitable LONG trade (entry=price, exit=price*1.01)
    entry_price = float(price)
    exit_price  = entry_price * 1.01
    qty_lots    = 1

    buy_value  = entry_price * unit_size * qty_lots
    sell_value = exit_price  * unit_size * qty_lots

    # Determine profile (futures or options doesn't matter here - use futures for all)
    profile = "mcx_futures"

    ef, _ = calculate_statutory_charges(profile, buy_value,  qty_lots, "BUY")
    xf, _ = calculate_statutory_charges(profile, sell_value, qty_lots, "SELL")

    gross_pnl     = (exit_price - entry_price) * unit_size * qty_lots
    total_charges = ef + xf
    net_pnl       = gross_pnl - total_charges

    # Sanity checks
    gross_ok   = gross_pnl > 0
    charges_ok = 0 < total_charges < gross_pnl  # charges should be < 100% of gross
    net_ok     = net_pnl > 0
    sane       = gross_ok and charges_ok and net_ok
    if not sane:
        all_pass = False

    flag = "[PASS]" if sane else "[FAIL]"
    print(f"  {symbol:<14} {unit_size:>5}  {price:>8,}  {buy_value:>12,.0f}  "
          f"{gross_pnl:>10,.2f}  {total_charges:>10,.2f}  {net_pnl:>10,.2f}  {flag}")
    print(f"  {'':14} {desc}")
    print()

print("="*90)
if all_pass:
    print("  [ALL PASS] Every commodity calculates sensible PnL and charges.")
else:
    print("  [SOME FAIL] Check above items marked [FAIL].")
print("="*90)

print("\n\nZERODHA VERIFIED RESULTS (exact match):")
print("-"*60)
# Re-run the two Zerodha-verified ones to confirm
for symbol, buy, sell, profile, expected_net, expected_charges in [
    ("CRUDEOIL (futures)", 6000, 6100, "mcx_futures", 9848.39, 151.61),
    ("GOLDM    (futures)", 100000, 100100, "mcx_futures", 780.76, 219.24),
    ("GOLD     (options)", 100, 110, "mcx_options", 936.92, 63.08),
]:
    unit_size = {"CRUDEOIL (futures)": 100, "GOLDM    (futures)": 10, "GOLD     (options)": 100}[symbol]
    buy_val  = buy  * unit_size
    sell_val = sell * unit_size
    ef, _ = calculate_statutory_charges(profile, buy_val,  1, "BUY")
    xf, _ = calculate_statutory_charges(profile, sell_val, 1, "SELL")
    gross  = (sell - buy) * unit_size
    total  = ef + xf
    net    = gross - total
    match  = abs(net - expected_net) < 0.5 and abs(total - expected_charges) < 0.5
    print(f"  {symbol}: Net={net:,.2f} (Zerodha:{expected_net})  Charges={total:,.2f} (Zerodha:{expected_charges})  "
          f"{'[PASS]' if match else '[FAIL]'}")
