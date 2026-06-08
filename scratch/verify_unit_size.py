"""
Verify the lot unit multiplier gap between our system and Zerodha's actual charges.

Zerodha calculator shows (CrudeOil, Buy=6000, Sell=6100, Qty=1):
  Futures:
    Turnover = 1,210,000  -> means (6000+6100)*100 = 1,210,000 -> 1 lot = 100 barrels
    CTT      = 61         -> 6100*100*0.0001 = 61 ✓
    ExchTxn  = 25.41      -> (6000+6100)*100*0.000021 = 25.41 ✓
    Net PnL  = 9,848.39   -> Gross = 100pts * 100bbl = 10,000
    Total charges = 151.61

  Options:
    Turnover = 1,210,000  (same underlying)
    CTT      = 305        -> 6100*100*0.0005 = 305 ✓
    ExchTxn  = 505.78     -> (6000+6100)*100*0.000418 = 506.18 ~ 505.78 ✓
    Net PnL  = 9,031.55   -> higher charges due to higher options txn fee
    Total charges = 968.45

Our system (before fix):
  CrudeOil at 6000, Futures, Qty=1
  Gross PnL = (6100-6000) * 1 = 100   <-- WRONG! Should be 10,000
  Charges calculated on value=6000     <-- WRONG! Should be 600,000
"""
import sys
sys.path.append('.')
from services.backtest_mcx_service import calculate_statutory_charges

# MCX CrudeOil: 1 lot = 100 barrels
UNIT_SIZE = 100

buy_price = 6000
sell_price = 6100
qty_lots = 1

buy_value  = buy_price  * UNIT_SIZE * qty_lots   # = 600,000
sell_value = sell_price * UNIT_SIZE * qty_lots   # = 610,000
turnover   = buy_value + sell_value               # = 1,210,000

print(f"\nCrudeOil Futures: Buy={buy_price}, Sell={sell_price}, Qty={qty_lots} lot(s)")
print(f"Unit size = {UNIT_SIZE} barrels/lot")
print(f"Buy value  = {buy_price} x {UNIT_SIZE} x {qty_lots} = {buy_value:,}")
print(f"Sell value = {sell_price} x {UNIT_SIZE} x {qty_lots} = {sell_value:,}")
print(f"Turnover   = {turnover:,}  (Zerodha shows: 1,210,000)")
assert turnover == 1210000, f"Turnover mismatch! Got {turnover}"
print("[PASS] Turnover matches Zerodha")

entry_fee, entry_bd = calculate_statutory_charges("mcx_futures", buy_value,  qty_lots, "BUY")
exit_fee,  exit_bd  = calculate_statutory_charges("mcx_futures", sell_value, qty_lots, "SELL")

gross_pnl = (sell_price - buy_price) * UNIT_SIZE * qty_lots  # = 10,000
net_pnl   = gross_pnl - entry_fee - exit_fee
total_charges = entry_fee + exit_fee

print(f"\n--- Entry charges (BUY) ---")
for k, v in entry_bd.items():
    print(f"  {k:12s}: {v:.2f}")

print(f"--- Exit charges (SELL) ---")
for k, v in exit_bd.items():
    print(f"  {k:12s}: {v:.2f}")

print(f"\nGross PnL     = {gross_pnl:,.2f}   (Zerodha gross: 10,000)")
print(f"Total charges = {total_charges:,.2f}   (Zerodha shows: 151.61)")
print(f"Net PnL       = {net_pnl:,.2f}   (Zerodha shows: 9,848.39)")

print(f"\n--- Verifying individual charges ---")
ctt_ours    = exit_bd['stt']
ctt_zerodha = 61.0
print(f"CTT:       ours={ctt_ours:.2f}  zerodha={ctt_zerodha}  {'[PASS]' if abs(ctt_ours-ctt_zerodha)<1 else '[FAIL]'}")

txn_ours    = entry_bd['txn'] + exit_bd['txn']
txn_zerodha = 25.41
print(f"Exch Txn:  ours={txn_ours:.2f}  zerodha={txn_zerodha}  {'[PASS]' if abs(txn_ours-txn_zerodha)<1 else '[FAIL]'}")

net_zerodha = 9848.39
print(f"Net PnL:   ours={net_pnl:.2f}  zerodha={net_zerodha}  {'[PASS]' if abs(net_pnl-net_zerodha)<5 else '[FAIL diff='+str(round(abs(net_pnl-net_zerodha),2))+']'}")

print("\n\n=== NOW MCX OPTIONS ===")
# For options, Zerodha calculates CTT on sell-side notional (strike * unit_size * qty)
# and txn on full turnover (both buy and sell notional)
strike = 6100
buy_prem  = 6000   # underlying price (Zerodha uses notional, not premium)
sell_prem = 6100   # underlying price

# Using underlying notional (like Zerodha)
buy_value_opt  = buy_prem  * UNIT_SIZE * qty_lots
sell_value_opt = sell_prem * UNIT_SIZE * qty_lots

entry_fee2, entry_bd2 = calculate_statutory_charges("mcx_options", buy_value_opt,  qty_lots, "BUY")
exit_fee2,  exit_bd2  = calculate_statutory_charges("mcx_options", sell_value_opt, qty_lots, "SELL")

gross_pnl2    = (sell_prem - buy_prem) * UNIT_SIZE * qty_lots  # = 10,000
net_pnl2      = gross_pnl2 - entry_fee2 - exit_fee2
total_charges2= entry_fee2 + exit_fee2

print(f"Gross PnL     = {gross_pnl2:,.2f}   (Zerodha gross: 10,000)")
print(f"Total charges = {total_charges2:,.2f}   (Zerodha shows: 968.45)")
print(f"Net PnL       = {net_pnl2:,.2f}   (Zerodha shows: 9,031.55)")

ctt2_ours    = exit_bd2['stt']
ctt2_zerodha = 305.0
print(f"\nCTT:       ours={ctt2_ours:.2f}  zerodha={ctt2_zerodha}  {'[PASS]' if abs(ctt2_ours-ctt2_zerodha)<1 else '[FAIL]'}")

txn2_ours    = entry_bd2['txn'] + exit_bd2['txn']
txn2_zerodha = 505.78
print(f"Exch Txn:  ours={txn2_ours:.2f}  zerodha={txn2_zerodha}  {'[PASS]' if abs(txn2_ours-txn2_zerodha)<5 else '[FAIL]'}")
