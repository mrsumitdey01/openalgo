"""
bot6/dtc_indicator.py
=====================
DTC (Dynamic Trend Confirmation) Indicator — pure Pandas/NumPy implementation.

Translates the TradingView Pine Script 6-EMA ribbon into vectorized Python.

CRITICAL ANTI-LOOKAHEAD DESIGN:
    All signals in the returned DataFrame are based on CLOSED bars only.
    The signal column at index [i] uses data from bars [0..i-1] — the
    current bar's close is NOT used to generate a signal for itself.
    This is enforced by computing trendUp/trendDown on the raw EMAs and
    then using .shift(1) to detect the crossover (not-trendUp[1]).

Pine Script equivalence:
    ma1 = ta.ema(close, 8)   → ema_8
    ma2 = ta.ema(close, 13)  → ema_13
    ma3 = ta.ema(close, 21)  → ema_21
    ma4 = ta.ema(close, 26)  → ema_26
    ma5 = ta.ema(close, 34)  → ema_34
    ma6 = ta.ema(close, 40)  → ema_40

    trendUp   = ma1>ma2 and ma2>ma3 and ma3>ma4 and ma4>ma5 and ma5>ma6
    trendDown = ma1<ma2 and ma2<ma3 and ma3<ma4 and ma4<ma5 and ma5<ma6

    buyCond  = trendUp and not trendUp[1]   → first bar of bullish alignment
    sellCond = trendDown and not trendDown[1] → first bar of bearish alignment
"""

import numpy as np
import pandas as pd
from config import EMA_LENGTHS


def _ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average using the standard decay formula
    matching TradingView's ta.ema() which uses alpha = 2/(period+1).
    adjust=False mirrors Pine Script's cumulative EMA behaviour.
    """
    return series.ewm(span=period, adjust=False).mean()


def compute_dtc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the full DTC ribbon and generate anti-lookahead signals.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain at minimum columns: ['open', 'high', 'low', 'close', 'volume']
        Index must be a DatetimeIndex (tz-aware or naive, IST recommended).

    Returns
    -------
    pd.DataFrame
        Original df with additional columns:
          ema_8, ema_13, ema_21, ema_26, ema_34, ema_40
          trend_up      : bool — all 6 EMAs in strict ascending order
          trend_down    : bool — all 6 EMAs in strict descending order
          buy_signal    : bool — first bar where trend flips to trend_up
          sell_signal   : bool — first bar where trend flips to trend_down
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("DataFrame index must be a DatetimeIndex.")

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    result = df.copy()
    close = result["close"]

    # --- Compute all 6 EMAs ---
    lengths = EMA_LENGTHS  # [8, 13, 21, 26, 34, 40]
    ema_cols = [f"ema_{l}" for l in lengths]
    for length, col in zip(lengths, ema_cols):
        result[col] = _ema(close, length)

    e8, e13, e21, e26, e34, e40 = [result[c] for c in ema_cols]

    # --- Strict alignment (mirrors Pine Script boolean logic) ---
    result["trend_up"] = (
        (e8 > e13) & (e13 > e21) & (e21 > e26) & (e26 > e34) & (e34 > e40)
    ).astype(bool)
    result["trend_down"] = (
        (e8 < e13) & (e13 < e21) & (e21 < e26) & (e26 < e34) & (e34 < e40)
    ).astype(bool)

    # --- ANTI-LOOKAHEAD SIGNAL GENERATION ---
    # Pine: buyCond  = trendUp   and not trendUp[1]
    # Pine: sellCond = trendDown and not trendDown[1]
    #
    # In Python, trendUp[1] means the PREVIOUS bar's trendUp.
    # We use .shift(1) on the CLOSED bar series.
    # The signal at bar[i] fires only after bar[i-1] is closed and
    # bar[i] has completed — meaning the execution happens on bar[i+1] open.
    # We mark the signal on bar[i] for transparency; the engine consumes
    # the PREVIOUS bar's signal before placing an order on the CURRENT bar open.
    # Use numpy arrays directly to avoid pandas FutureWarning on fillna
    _up = result["trend_up"].to_numpy(dtype=bool)
    _dn = result["trend_down"].to_numpy(dtype=bool)
    prev_up = np.concatenate([[False], _up[:-1]])
    prev_dn = np.concatenate([[False], _dn[:-1]])

    result["buy_signal"] = _up & ~prev_up
    result["sell_signal"] = _dn & ~prev_dn

    return result


def get_actionable_signals(df_with_dtc: pd.DataFrame) -> pd.DataFrame:
    """
    Produce the final signal DataFrame where signals are shifted by 1 bar
    so that signal[i] = True means: "enter at bar[i+1] open price".

    This is the strict no-lookahead execution layer. The engine reads
    `action_buy` or `action_sell` from the CURRENT bar before placing orders.

    Returns
    -------
    pd.DataFrame with columns: action_buy, action_sell
        True on bar N means execute at bar N's open (signal was on bar N-1).
    """
    out = df_with_dtc[["buy_signal", "sell_signal"]].copy()

    # Use numpy to avoid pandas FutureWarning on fillna with object dtype
    _buy = out["buy_signal"].to_numpy(dtype=bool)
    _sell = out["sell_signal"].to_numpy(dtype=bool)
    out["action_buy"] = np.concatenate([[False], _buy[:-1]])
    out["action_sell"] = np.concatenate([[False], _sell[:-1]])

    return out[["action_buy", "action_sell"]]
