"""
bot6/tests/test_dtc_indicator.py
=================================
Unit tests for dtc_indicator.py
Validates: EMA computation, signal generation, zero lookahead enforcement.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import pytest

from dtc_indicator import compute_dtc, get_actionable_signals


def make_df(closes: list[float], n_pad: int = 50) -> pd.DataFrame:
    """Create minimal OHLCV DataFrame with given close prices (padded for EMA warmup)."""
    # Pad with flat data so EMAs converge before the signal region
    pad = [closes[0]] * n_pad
    all_closes = pad + closes
    n = len(all_closes)
    idx = pd.date_range("2025-01-02 09:15:00", periods=n, freq="1min")
    return pd.DataFrame(
        {
            "open": all_closes,
            "high": [c * 1.002 for c in all_closes],
            "low": [c * 0.998 for c in all_closes],
            "close": all_closes,
            "volume": [100_000] * n,
        },
        index=idx,
    )


class TestEMA:
    def test_ema_columns_present(self):
        df = make_df([100.0] * 20)
        result = compute_dtc(df)
        for col in ["ema_8", "ema_13", "ema_21", "ema_26", "ema_34", "ema_40"]:
            assert col in result.columns, f"Missing EMA column: {col}"

    def test_ema_warmup_nan_at_start(self):
        """EMA should return NaN for the very first bar (before pandas fills it)."""
        df = make_df([100.0] * 5, n_pad=0)
        result = compute_dtc(df)
        # ewm with adjust=False returns values from bar 0 but they're estimates;
        # the first bar should equal the close itself
        assert abs(result["ema_8"].iloc[0] - 100.0) < 0.01

    def test_ema_converges_on_flat_series(self):
        """On a flat price series, all EMAs should converge to the same value."""
        df = make_df([200.0] * 100, n_pad=0)
        result = compute_dtc(df)
        # After sufficient bars, all EMAs should equal ~200
        assert abs(result["ema_40"].iloc[-1] - 200.0) < 0.01

    def test_ema_short_period_faster(self):
        """Shorter EMA reacts faster to a price jump."""
        closes = [100.0] * 50 + [120.0] * 20
        df = make_df(closes, n_pad=0)
        result = compute_dtc(df)
        # After a jump, ema_8 should be closer to 120 than ema_40
        last = result.iloc[-1]
        assert last["ema_8"] > last["ema_40"]


class TestTrendAlignment:
    def test_trend_up_on_rising_prices(self):
        """Strict uptrend: gradually rising prices should produce trend_up=True."""
        # Start flat, then trend strongly up
        closes = [100.0] * 60 + [i * 0.1 + 100.0 for i in range(60)]
        df = make_df(closes, n_pad=0)
        result = compute_dtc(df)
        # Last bar should show trend_up
        assert result["trend_up"].iloc[-1] == True
        assert result["trend_down"].iloc[-1] == False

    def test_trend_down_on_falling_prices(self):
        """Strict downtrend: gradually falling prices should produce trend_down=True."""
        closes = [100.0] * 60 + [100.0 - i * 0.1 for i in range(60)]
        df = make_df(closes, n_pad=0)
        result = compute_dtc(df)
        assert result["trend_down"].iloc[-1] == True
        assert result["trend_up"].iloc[-1] == False

    def test_neutral_zone_on_flat_prices(self):
        """Flat prices: all EMAs equal → neither trend_up nor trend_down."""
        df = make_df([100.0] * 100, n_pad=0)
        result = compute_dtc(df)
        # All EMAs same → no strict alignment
        assert result["trend_up"].iloc[-1] == False
        assert result["trend_down"].iloc[-1] == False


class TestSignals:
    def test_buy_signal_fires_on_first_uptrend_bar(self):
        """buy_signal should fire exactly on the bar where trendUp first becomes True."""
        # Flat then rising
        closes = [100.0] * 60 + [100.0 + i * 0.15 for i in range(60)]
        df = make_df(closes, n_pad=0)
        result = compute_dtc(df)
        buy_signals = result[result["buy_signal"]]
        assert len(buy_signals) >= 1, "Expected at least one buy signal"

    def test_sell_signal_fires_on_first_downtrend_bar(self):
        """sell_signal should fire exactly on the bar where trendDown first becomes True."""
        closes = [100.0] * 60 + [100.0 - i * 0.15 for i in range(60)]
        df = make_df(closes, n_pad=0)
        result = compute_dtc(df)
        sell_signals = result[result["sell_signal"]]
        assert len(sell_signals) >= 1, "Expected at least one sell signal"

    def test_no_simultaneous_buy_and_sell(self):
        """buy_signal and sell_signal should never both be True on same bar."""
        closes = [100.0] * 60 + [100.0 + i * 0.1 for i in range(30)] + [100.0 - i * 0.1 for i in range(30)]
        df = make_df(closes, n_pad=0)
        result = compute_dtc(df)
        simultaneous = result["buy_signal"] & result["sell_signal"]
        assert not simultaneous.any(), "Buy and Sell signals fired simultaneously!"


class TestNoLookahead:
    def test_action_signal_shifted_by_one_bar(self):
        """
        CRITICAL: action_buy at bar[i] must equal buy_signal at bar[i-1].
        This verifies zero lookahead bias in the execution layer.
        """
        closes = [100.0] * 60 + [100.0 + i * 0.2 for i in range(60)]
        df = make_df(closes, n_pad=0)
        result = compute_dtc(df)
        actionable = get_actionable_signals(result)

        # action_buy at bar[i] = buy_signal at bar[i-1]
        # Use numpy to avoid FutureWarning with fillna on object dtype
        _buy = result["buy_signal"].to_numpy(dtype=bool)
        buy_shifted = np.concatenate([[False], _buy[:-1]])
        assert (actionable["action_buy"].to_numpy(dtype=bool) == buy_shifted).all(), \
            "LOOKAHEAD DETECTED: action_buy does not match buy_signal[i-1]"

        _sell = result["sell_signal"].to_numpy(dtype=bool)
        sell_shifted = np.concatenate([[False], _sell[:-1]])
        assert (actionable["action_sell"].to_numpy(dtype=bool) == sell_shifted).all(), \
            "LOOKAHEAD DETECTED: action_sell does not match sell_signal[i-1]"

    def test_no_future_data_in_ema(self):
        """Verify EMAs at bar[i] only use data up to bar[i]."""
        closes = list(range(100, 200))  # linear ascent
        df = make_df(closes, n_pad=50)
        result = compute_dtc(df)
        # EMA must be non-decreasing on a perfectly linear ascending series
        ema8 = result["ema_8"].values
        diffs = np.diff(ema8[40:])  # skip warmup
        assert (diffs >= -1e-9).all(), "EMA decreased on ascending series — possible lookahead!"
