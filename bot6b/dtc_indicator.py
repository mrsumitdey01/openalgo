"""
bot6b/dtc_indicator.py
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
try:
    from bot6b.config import (
        EMA_LENGTHS,
        USE_VWAP_FILTER,
        USE_RVOL_FILTER,
        RVOL_THRESHOLD,
        RVOL_LENGTH,
    )
except ImportError:
    from config import (
        EMA_LENGTHS,
        USE_VWAP_FILTER,
        USE_RVOL_FILTER,
        RVOL_THRESHOLD,
        RVOL_LENGTH,
    )


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

    # --- Calculate Contextual Filters (VWAP & RVOL) ---
    # 1. VWAP (Daily Reset)
    typical_price = (result["high"] + result["low"] + result["close"]) / 3
    vwap_vol = result["volume"] * typical_price
    
    # Calculate cumulative sums grouped by date
    # In Pandas, if index is datetime, we can group by index.date
    # But doing this vectorized over a continuous dataframe is faster.
    daily_groups = result.index.floor('D')
    cum_vol = result["volume"].groupby(daily_groups).cumsum()
    cum_vwap_vol = vwap_vol.groupby(daily_groups).cumsum()
    result["vwap"] = cum_vwap_vol / cum_vol

    # 2. RVOL (Relative Volume)
    sma_vol = result["volume"].rolling(window=RVOL_LENGTH, min_periods=1).mean()
    # Replace 0 with NaN to avoid division by zero
    result["rvol"] = result["volume"] / sma_vol.replace(0, np.nan)
    # Fill NaN with 0 (e.g. if sma_vol was 0)
    result["rvol"] = result["rvol"].fillna(0)

    # --- ANTI-LOOKAHEAD SIGNAL GENERATION ---
    _up = result["trend_up"].to_numpy(dtype=bool)
    _dn = result["trend_down"].to_numpy(dtype=bool)
    
    _close = result["close"].to_numpy()
    _ema8 = result["ema_8"].to_numpy()

    # LONG: Established uptrend AND close > dtc max ribbon (ema_8)
    close_above_max = _close > _ema8
    
    # We use .shift(1) on the CLOSED bar series for the base signal
    prev_up = np.concatenate([[False], _up[:-1]])
    prev_close_above = np.concatenate([[False], close_above_max[:-1]])
    
    buy_base = _up & ~prev_up & close_above_max

    # SHORT: Established downtrend AND close < dtc min ribbon (ema_8)
    close_below_min = _close < _ema8
    prev_dn = np.concatenate([[False], _dn[:-1]])
    sell_base = _dn & ~prev_dn & close_below_min

    # Apply contextual filters
    _close = result["close"].to_numpy()
    _vwap = result["vwap"].to_numpy()
    _rvol = result["rvol"].to_numpy()

    vwap_long_cond = (_close > _vwap) if USE_VWAP_FILTER else True
    vwap_short_cond = (_close < _vwap) if USE_VWAP_FILTER else True
    rvol_cond = (_rvol >= RVOL_THRESHOLD) if USE_RVOL_FILTER else True

    result["buy_signal"] = buy_base & vwap_long_cond & rvol_cond
    result["sell_signal"] = sell_base & vwap_short_cond & rvol_cond

    result.drop(columns=["vwap", "rvol"], inplace=True, errors='ignore')
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
    
    # Base shifted signals
    shifted_buy = np.concatenate([[False], _buy[:-1]])
    shifted_sell = np.concatenate([[False], _sell[:-1]])

    # "Open matching the trade": For LONG, the execution bar's open must be 
    # above the dtc max ribbon (ema_8). For SHORT, it must be below dtc min (ema_8).
    # This prevents entering if the market gaps heavily against the signal.
    _open = df_with_dtc["open"].to_numpy()
    _ema8 = df_with_dtc["ema_8"].to_numpy()

    open_matches_long = _open > _ema8
    open_matches_short = _open < _ema8

    out["action_buy"] = shifted_buy & open_matches_long
    out["action_sell"] = shifted_sell & open_matches_short

    return out[["action_buy", "action_sell"]]
