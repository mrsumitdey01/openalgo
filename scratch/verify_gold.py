"""
Verify GOLDM and GOLD unit sizes against Zerodha's calculator.

From screenshot:
  GOLDM Futures: Buy=100000, Sell=100100, Qty=1
    Turnover = 2,001,000
    CTT      = 100.1
    Exch Txn = 42.02
    Stamp    = 20
    Total    = 219.24
    Net PnL  = 780.76 (Gross = 1000)

  GOLD Options: Strike=100000, Buy premium=100, Sell premium=110, Qty=1
    Turnover = 21,000
    CTT      = 5.5
    Exch Txn = 8.78 (both buy+sell)
    Total    = 63.08
    Net PnL  = 936.92 (Gross = (110-100)*unit_size)
"""
import sys
sys.path.append('.')
from services.backtest_mcx_service import calculate_statutory_charges

# ── Derive unit sizes from Zerodha turnover ──────────────────────────────────
goldm_turnover_zerodha = 2_001_000
goldm_price_sum = 100000 + 100100   # 200,100
goldm_unit_size = goldm_turnover_zerodha // goldm_price_sum
print(f"GOLDM unit_size = {goldm_turnover_zerodha} / {goldm_price_sum} = {goldm_unit_size}")

gold_turnover_zerodha = 21_000
gold_premium_sum = 100 + 110   # 210
gold_unit_size = gold_turnover_zerodha // gold_premium_sum
print(f"GOLD  unit_size = {gold_turnover_zerodha} / {gold_premium_sum} = {gold_unit_size}")

print()

# ── Verify GOLDM Futures ──────────────────────────────────────────────────────
print("=" * 60)
print("GOLDM Futures  (Buy=100000, Sell=100100, Qty=1 lot)")
print("=" * 60)
buy_val  = 100000 * goldm_unit_size * 1   # 1,000,000
sell_val = 100100 * goldm_unit_size * 1   # 1,001,000
turnover = buy_val + sell_val             # 2,001,000
print(f"Buy value  = {buy_val:,}   Sell value = {sell_val:,}")
print(f"Turnover   = {turnover:,}   (Zerodha: 2,001,000)  {'[PASS]' if turnover==2_001_000 else '[FAIL]'}")

ef, ebd = calculate_statutory_charges("mcx_futures", buy_val,  1, "BUY")
xf, xbd = calculate_statutory_charges("mcx_futures", sell_val, 1, "SELL")

print(f"\nEntry fees: {ef:.2f}  |  Exit fees: {xf:.2f}")
total_charges = ef + xf
gross_pnl = (100100 - 100000) * goldm_unit_size * 1   # 1,000
net_pnl   = gross_pnl - total_charges

print(f"\nGross PnL     = {gross_pnl:,.2f}   (expected: 1,000)")
print(f"Total charges = {total_charges:,.2f}   (Zerodha: 219.24)")
print(f"Net PnL       = {net_pnl:,.2f}   (Zerodha: 780.76)")
print(f"CTT           = {xbd['stt']:.2f}   (Zerodha: 100.1)")
print(f"Txn charges   = {ebd['txn']+xbd['txn']:.2f}   (Zerodha: 42.02)")
print(f"Stamp         = {ebd['stamp']:.2f}   (Zerodha: 20)")

print(f"\n[{'PASS' if abs(net_pnl-780.76)<0.1 else 'FAIL'}] Net PnL  |  "
      f"[{'PASS' if abs(total_charges-219.24)<0.5 else 'FAIL'}] Total charges")

# ── Verify GOLD Options ───────────────────────────────────────────────────────
print()
print("=" * 60)
print("GOLD Options  (Strike=100000, Buy prem=100, Sell prem=110, Qty=1)")
print("=" * 60)
buy_val2  = 100  * gold_unit_size * 1   # 10,000
sell_val2 = 110  * gold_unit_size * 1   # 11,000
turnover2 = buy_val2 + sell_val2        # 21,000
print(f"Buy value  = {buy_val2:,}   Sell value = {sell_val2:,}")
print(f"Turnover   = {turnover2:,}   (Zerodha: 21,000)  {'[PASS]' if turnover2==21_000 else '[FAIL]'}")

ef2, ebd2 = calculate_statutory_charges("mcx_options", buy_val2,  1, "BUY")
xf2, xbd2 = calculate_statutory_charges("mcx_options", sell_val2, 1, "SELL")

total_charges2 = ef2 + xf2
gross_pnl2 = (110 - 100) * gold_unit_size * 1   # 1,000
net_pnl2   = gross_pnl2 - total_charges2

print(f"\nGross PnL     = {gross_pnl2:,.2f}   (expected: 1,000)")
print(f"Total charges = {total_charges2:,.2f}   (Zerodha: 63.08)")
print(f"Net PnL       = {net_pnl2:,.2f}   (Zerodha: 936.92)")
print(f"CTT           = {xbd2['stt']:.2f}   (Zerodha: 5.5)")
print(f"Txn charges   = {ebd2['txn']+xbd2['txn']:.2f}   (Zerodha: 8.78)")

print(f"\n[{'PASS' if abs(net_pnl2-936.92)<0.5 else 'FAIL'}] Net PnL  |  "
      f"[{'PASS' if abs(total_charges2-63.08)<0.5 else 'FAIL'}] Total charges")
