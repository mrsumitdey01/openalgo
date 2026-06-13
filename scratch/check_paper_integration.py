import sys
sys.path.insert(0, '.')

import inspect
from database.historify_db import get_ohlcv
sig = inspect.signature(get_ohlcv)
print(f"[OK] get_ohlcv signature: {sig}")

from services.quotes_service import get_quotes
sig2 = inspect.signature(get_quotes)
print(f"[OK] get_quotes signature: {sig2}")

# Test the DB call as paper_trade_service.py makes it
import time
end_ts = int(time.time())
start_ts = end_ts - (3 * 86400)
df = get_ohlcv(symbol='BANKNIFTY', exchange='NSE_INDEX', interval='1m', start_timestamp=start_ts, end_timestamp=end_ts)
print(f"[OK] get_ohlcv returned {len(df)} rows")
print(f"     columns: {list(df.columns)}")
if len(df) > 0:
    last = df.iloc[-1]
    print(f"     last candle ts: {last['timestamp']}, close: {last['close']}")

# Test the _prepare_indicators path specifically for bot4
import pandas as pd
from services.paper_trade_service import _prepare_indicators, _get_signal

# Build a minimal test df (bot4 doesn't use any indicators, so this should be a no-op)
if len(df) > 10:
    df_sorted = df.sort_values("timestamp").reset_index(drop=True)
    df_sorted["datetime"] = df_sorted["timestamp"].apply(
        lambda t: __import__('datetime').datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    )
    try:
        df_ind = _prepare_indicators(df_sorted, "bot4")
        print(f"[OK] _prepare_indicators(bot4) ran OK, returned df shape: {df_ind.shape}")
        # Test signal at last candle (should be HOLD outside of 9:21)
        sig = _get_signal(df_ind, len(df_ind)-1, "bot4", None)
        print(f"[OK] _get_signal(bot4) at last candle = {sig}")
    except Exception as e:
        print(f"[FAIL] _prepare_indicators error: {e}")
        import traceback
        traceback.print_exc()
else:
    print("[WARN] Not enough DB data to test indicators, DB may be empty for NSE_INDEX/BANKNIFTY")

print("\n=== FULL INTEGRATION CHECK DONE ===")
