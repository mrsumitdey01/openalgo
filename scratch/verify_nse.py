"""
Verify NSE statutory charges against Zerodha calculator.
For NSE:
  BankNifty Futures: Spot=50000, Exit=50100, Qty=30 (1 lot)
    Turnover = (50000 + 50100) * 30 = 3,003,000
    Brokerage = 40 (20/leg)
    STT = 50100 * 30 * 0.000125 = 187.875
    Txn = 3003000 * 0.000019 = 57.057
    Stamp = 50000 * 30 * 0.00002 = 30
    Net PnL = (50100-50000) * 30 - TotalCharges

  BankNifty Options: Spot=50000
    Let's say option premium is entry=200, exit=250, Qty=30
    Turnover = (200 + 250) * 30 = 13,500
    STT = 250 * 30 * 0.00125 (wait, options STT is 0.125% or 0.1%?)
      Actually, STT on options is 0.125% on sell premium. Wait, let's check our code.
      Code has `stt = value * 0.0015` -> 0.15% ? Wait, government increased STT on options to 0.1% and futures to 0.02% from Oct 1 2024?
      Let's verify what values we get compared to our formula.
"""
import sys
sys.path.append('.')
from services.backtest_service import calculate_statutory_charges

print("--- NSE BankNifty Futures (1 Lot = 30 shares) ---")
buy_price = 50000
sell_price = 50100
qty = 30 # User inputs 30

buy_val = buy_price * qty
sell_val = sell_price * qty
print(f"Buy Value: {buy_val}, Sell Value: {sell_val}, Turnover: {buy_val + sell_val}")

ef, ebd = calculate_statutory_charges("fo_futures", buy_val, qty, "BUY")
xf, xbd = calculate_statutory_charges("fo_futures", sell_val, qty, "SELL")

gross = (sell_price - buy_price) * qty
total = ef + xf
net = gross - total

print(f"Gross PnL: {gross}")
print(f"Entry Fees: {ef:.2f}")
for k, v in ebd.items():
    print(f"  {k}: {v}")
print(f"Exit Fees: {xf:.2f}")
for k, v in xbd.items():
    print(f"  {k}: {v}")
print(f"Total Charges: {total:.2f}")
print(f"Net PnL: {net:.2f}")

print("\n--- NSE BankNifty Options (1 Lot = 30 shares) ---")
# Simulate options spread mode where premium = spot * 0.005
buy_prem = 50000 * 0.005 # 250
sell_prem = buy_prem + 10 # 260
buy_val_opt = buy_prem * qty
sell_val_opt = sell_prem * qty

print(f"Buy Value: {buy_val_opt}, Sell Value: {sell_val_opt}, Turnover: {buy_val_opt + sell_val_opt}")

ef2, ebd2 = calculate_statutory_charges("fo_options", buy_val_opt, qty, "BUY")
xf2, xbd2 = calculate_statutory_charges("fo_options", sell_val_opt, qty, "SELL")

gross2 = (sell_prem - buy_prem) * qty
total2 = ef2 + xf2
net2 = gross2 - total2

print(f"Gross PnL: {gross2}")
print(f"Entry Fees: {ef2:.2f}")
for k, v in ebd2.items():
    print(f"  {k}: {v}")
print(f"Exit Fees: {xf2:.2f}")
for k, v in xbd2.items():
    print(f"  {k}: {v}")
print(f"Total Charges: {total2:.2f}")
print(f"Net PnL: {net2:.2f}")

