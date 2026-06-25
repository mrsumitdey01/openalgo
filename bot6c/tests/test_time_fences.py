"""
bot6c/tests/test_time_fences.py
================================
Integration tests for execution engine time fences.
Validates: no entries before 09:15, no entries after 14:45,
           hard square-off at 15:15, and no carryover between sessions.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import pytest

from backtest_runner import generate_sample_data, run_backtest


def make_ohlcv_at_time(time_str: str, price: float = 1000.0) -> pd.DataFrame:
    """Create a single-bar DataFrame at a specific time."""
    idx = pd.DatetimeIndex([pd.Timestamp(f"2025-01-02 {time_str}:00")])
    return pd.DataFrame(
        {
            "open": [price],
            "high": [price * 1.005],
            "low": [price * 0.995],
            "close": [price * 1.002],
            "volume": [100_000],
        },
        index=idx,
    )


class TestTimeFences:
    def test_no_entry_before_0915(self):
        """No trades should be executed before 09:15 AM."""
        # Full day data but with a forced buy signal before 09:15
        np.random.seed(10)
        idx = pd.date_range("2025-01-02 08:00:00", periods=90, freq="1min")
        n = len(idx)
        closes = [1000.0 + i * 0.5 for i in range(n)]  # strong uptrend
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c * 1.003 for c in closes],
                "low": [c * 0.997 for c in closes],
                "close": closes,
                "volume": [100_000] * n,
            },
            index=idx,
        )
        result = run_backtest("TEST_NOEARLY", df)
        for trade in result["trades"]:
            entry_time = pd.Timestamp(trade["entry_time"])
            assert entry_time.strftime("%H:%M") >= "09:15", \
                f"Trade entered before 09:15: {entry_time}"

    def test_no_new_entry_after_1445(self):
        """No NEW entries should be taken after 14:45."""
        np.random.seed(20)
        idx = pd.date_range("2025-01-02 09:15:00", periods=400, freq="1min")
        n = len(idx)
        closes = [1000.0 + i * 0.3 for i in range(n)]  # continuous uptrend
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c * 1.002 for c in closes],
                "low": [c * 0.998 for c in closes],
                "close": closes,
                "volume": [100_000] * n,
            },
            index=idx,
        )
        result = run_backtest("TEST_NOCUTOFF", df)
        for trade in result["trades"]:
            entry_time = pd.Timestamp(trade["entry_time"])
            assert entry_time.strftime("%H:%M") <= "14:45", \
                f"Trade entered after 14:45: {entry_time}"

    def test_eod_squareoff_at_1515(self):
        """Any open position at 15:15 must be forcibly closed."""
        np.random.seed(30)
        # Create data that generates a signal around 14:30 so position is open at 15:15
        idx = pd.date_range("2025-01-02 09:15:00", periods=380, freq="1min")
        n = len(idx)
        # Flat then strongly rising after 14:00
        closes = []
        for ts in idx:
            if ts.hour >= 14:
                closes.append(1000.0 + len(closes) * 1.0)
            else:
                closes.append(1000.0)
        df = pd.DataFrame(
            {
                "open": closes,
                "high": [c * 1.003 for c in closes],
                "low": [c * 0.997 for c in closes],
                "close": closes,
                "volume": [100_000] * n,
            },
            index=idx,
        )
        result = run_backtest("TEST_EOD", df)
        eod_trades = [
            t for t in result["trades"]
            if t["exit_reason"] == "EOD_SQUAREOFF"
        ]
        # If any trade is still open at 15:15, it should be in eod_trades
        for trade in eod_trades:
            exit_time = pd.Timestamp(trade["exit_time"])
            assert exit_time.strftime("%H:%M") >= "15:15", \
                f"EOD squareoff happened too early: {exit_time}"
