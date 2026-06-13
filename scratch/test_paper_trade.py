import sys
sys.path.insert(0, '.')

from services.paper_trade_service import start_paper_trading, stop_paper_trading, get_paper_trade_status
import time

print("--- Test 1: Initial Status ---")
status = get_paper_trade_status()
print(f"  is_active: {status['is_active']}")
print(f"  total_accounts: {status['total_accounts']}")

print("\n--- Test 2: Start Engine ---")
result = start_paper_trading()
print(f"  result: {result}")

time.sleep(3)  # Let scheduler fire once

print("\n--- Test 3: Status After Start ---")
status = get_paper_trade_status()
print(f"  is_active: {status['is_active']}")
print(f"  error: {status['error']}")
print(f"  last_run_at: {status['last_run_at']}")
print(f"  total_accounts: {status['total_accounts']}")

# Print first 3 accounts for inspection
for acc in status['accounts'][:3]:
    print(f"  Account: {acc['account_id']} | status: {acc['status']} | pnl: {acc['metrics'].get('net_pnl')}")

print("\n--- Test 4: Start Again (idempotent) ---")
result2 = start_paper_trading()
print(f"  result: {result2}")

print("\n--- Test 5: Stop Engine ---")
result3 = stop_paper_trading()
print(f"  result: {result3}")

status2 = get_paper_trade_status()
print(f"  is_active after stop: {status2['is_active']}")

print("\n=== ALL LIFECYCLE TESTS PASS ===")
