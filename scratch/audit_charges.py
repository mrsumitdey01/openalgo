"""
Detailed audit of statutory charges correctness per trade.
Picks sample trades and manually recomputes charges to verify.
"""
import sys
sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot1_backtest, calculate_statutory_charges

# Run a small test to get trades with fee breakdowns
params = {
    'symbol': 'BANKNIFTY',
    'exchange': 'NSE_INDEX',
    'start_date': '2025-01-01',
    'end_date': '2025-01-31',
    'capital': 300000,
    'lot_size': 30,
    'execution_mode': 'options_spread'  # uses fo_options charges
}

success, response, code = run_bot1_backtest(params)
trades = response['trades']

print("=" * 100)
print("STATUTORY CHARGES AUDIT - fo_options profile (Options Spread)")
print("=" * 100)
print()

# Verify formula for fo_options:
# Brokerage: Rs. 20 flat per order
# STT: 0.15% on SELL side only (0.0015 * value)
# Transaction charges: 0.03553% (0.0003553 * value)
# SEBI: 0.0001% (0.000001 * value)
# Stamp duty: 0.003% on BUY side only (0.00003 * value)
# GST: 18% on (brokerage + SEBI + txn)
print("Expected fo_options formula:")
print("  Brokerage = Rs. 20 flat")
print("  STT       = 0.15% of value (SELL only)")
print("  Txn       = 0.03553% of value")
print("  SEBI      = 0.0001% of value")
print("  Stamp     = 0.003% of value (BUY only)")
print("  GST       = 18% of (brokerage + SEBI + txn)")
print()

for t in trades[:5]:
    print(f"--- Trade #{t['id']} ({t['direction']}) ---")
    print(f"  Entry: {t['entry_time']} @ {t['entry_price']}, Exit: {t['exit_time']} @ {t['exit_price']}")
    print(f"  Qty: {t['qty']}")
    
    fb = t.get('fee_breakdown', {})
    print(f"  Fee Breakdown (from backtest):")
    print(f"    Brokerage: {fb.get('brokerage', '?')}")
    print(f"    STT:       {fb.get('stt', '?')}")
    print(f"    Txn:       {fb.get('txn', '?')}")
    print(f"    GST:       {fb.get('gst', '?')}")
    print(f"    SEBI:      {fb.get('sebi', '?')}")
    print(f"    Stamp:     {fb.get('stamp', '?')}")
    print(f"    Total:     {fb.get('total', '?')}")
    
    # Manually recompute exit charges
    exit_spread = t['exit_price']
    qty = t['qty']
    exit_value = abs(exit_spread * qty)
    exit_side = "BUY" if t['direction'] == "SHORT" else "SELL"
    
    manual_brokerage = 20.0
    manual_stt = (exit_value * 0.0015) if exit_side == "SELL" else 0.0
    manual_txn = exit_value * 0.0003553
    manual_sebi = exit_value * 0.000001
    manual_stamp = (exit_value * 0.00003) if exit_side == "BUY" else 0.0
    manual_gst = (manual_brokerage + manual_sebi + manual_txn) * 0.18
    manual_total = manual_brokerage + manual_stt + manual_txn + manual_gst + manual_sebi + manual_stamp
    
    print(f"  Manual recompute (exit side={exit_side}, exit_value={exit_value:.2f}):")
    print(f"    Brokerage: {manual_brokerage:.2f}")
    print(f"    STT:       {manual_stt:.2f}")
    print(f"    Txn:       {manual_txn:.2f}")
    print(f"    GST:       {manual_gst:.2f}")
    print(f"    SEBI:      {manual_sebi:.2f}")
    print(f"    Stamp:     {manual_stamp:.2f}")
    print(f"    Total:     {manual_total:.2f}")
    
    match = abs(fb.get('total', 0) - round(manual_total, 2)) < 0.05
    print(f"  Match: {'YES' if match else 'NO - MISMATCH!'}")
    
    # Capital accounting check
    print(f"  gross_pnl={t['gross_pnl']:.2f}, entry_fee={t['entry_fee']:.2f}, exit_fee={t['exit_fee']:.2f}")
    expected_net = round(t['gross_pnl'] - t['entry_fee'] - t['exit_fee'], 2)
    print(f"  net_pnl={t['net_pnl']:.2f}, expected={expected_net:.2f}, match={'YES' if abs(t['net_pnl'] - expected_net) < 0.02 else 'NO!'}")
    print()

# Also verify the entry fee for the first trade
print("=" * 100)
print("ENTRY FEE VERIFICATION (Trade #1)")
print("=" * 100)
t = trades[0]
entry_spread = t['entry_price']
qty = t['qty']
entry_value = abs(entry_spread * qty)
entry_side = "SELL" if t['direction'] == "SHORT" else "BUY"

# Recompute
man_brk = 20.0
man_stt = (entry_value * 0.0015) if entry_side == "SELL" else 0.0
man_txn = entry_value * 0.0003553
man_sebi = entry_value * 0.000001
man_stamp = (entry_value * 0.00003) if entry_side == "BUY" else 0.0
man_gst = (man_brk + man_sebi + man_txn) * 0.18
man_total = man_brk + man_stt + man_txn + man_gst + man_sebi + man_stamp

print(f"  Direction: {t['direction']}, Entry side: {entry_side}")
print(f"  entry_spread={entry_spread}, qty={qty}, entry_value={entry_value:.2f}")
print(f"  Reported entry_fee: {t['entry_fee']}")
print(f"  Manual recompute:   {round(man_total, 2)}")
print(f"  Match: {'YES' if abs(t['entry_fee'] - round(man_total, 2)) < 0.05 else 'NO!'}")
print()

# Capital reconciliation: check that summing all trades' net_pnl gives the correct final capital
print("=" * 100)
print("CAPITAL RECONCILIATION")
print("=" * 100)
initial = 300000
total_net_pnl = sum(t['net_pnl'] for t in trades)
expected_final = initial + total_net_pnl
reported_final = response['metrics']['final_capital']
print(f"  Initial Capital:   Rs. {initial:,.2f}")
print(f"  Sum of net_pnl:    Rs. {total_net_pnl:,.2f}")
print(f"  Expected Final:    Rs. {expected_final:,.2f}")
print(f"  Reported Final:    Rs. {reported_final:,.2f}")
print(f"  Difference:        Rs. {abs(expected_final - reported_final):,.2f}")
print(f"  Match: {'YES' if abs(expected_final - reported_final) < 1.0 else 'NO - MISMATCH!'}")
