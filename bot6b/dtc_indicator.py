"""
bot6b/dtc_indicator.py
=====================
Holy Grail Confluence Mean-Revert Indicator

Executes the proven Mean Reversion strategy: Fading extreme price movements back to the VWAP.

CRITICAL ANTI-LOOKAHEAD DESIGN:
    All signals in the returned DataFrame are based on CLOSED bars only.
"""

import numpy as np
import pandas as pd

def compute_dtc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the Confluence Mean-Revert signals.
    Retains the original function name for backwards compatibility with the execution engine.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("DataFrame index must be a DatetimeIndex.")

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    result = df.copy()
    
    # 1. Compute 20-period volume SMA for RVOL
    sma_vol = result["volume"].rolling(window=20, min_periods=1).mean()
    result["rvol"] = result["volume"] / sma_vol.replace(0, np.nan)
    result["rvol"] = result["rvol"].fillna(0)
    
    # 2. Compute Intraday VWAP
    # VWAP resets every day
    daily_groups = result.groupby(result.index.floor('D'))
    
    vwaps = pd.Series(index=result.index, dtype=float)
    
    for date, group in daily_groups:
        typical_price = (group['high'] + group['low'] + group['close']) / 3
        vol_tp = group['volume'] * typical_price
        
        cum_vol_tp = vol_tp.cumsum()
        cum_vol = group['volume'].cumsum()
        
        vwaps.loc[group.index] = cum_vol_tp / cum_vol.replace(0, np.nan)
        
    result['vwap'] = vwaps
    
    # 4. Entry Conditions
    times = result.index.time
    time_mask = (times >= pd.to_datetime('09:30').time()) & (times <= pd.to_datetime('11:00').time())
    
    # LONG: Price crashes 1.5% below VWAP with high relative volume
    buy_cond = (result["close"] < (result["vwap"] * 0.985)) & (result["rvol"] > 2.0) & time_mask
    
    # SHORT: Price pumps 1.5% above VWAP with high relative volume
    sell_cond = (result["close"] > (result["vwap"] * 1.015)) & (result["rvol"] > 2.0) & time_mask

    # To ensure signal triggers only ONCE when condition is first met, we compare to previous bar
    _buy = buy_cond.to_numpy()
    _sell = sell_cond.to_numpy()
    
    prev_buy = np.concatenate([[False], _buy[:-1]])
    prev_sell = np.concatenate([[False], _sell[:-1]])
    
    result["buy_signal"] = _buy & ~prev_buy
    result["sell_signal"] = _sell & ~prev_sell

    return result

def get_actionable_signals(df_with_dtc: pd.DataFrame) -> pd.DataFrame:
    """
    Produce the final signal DataFrame where signals are shifted by 1 bar
    so that signal[i] = True means: "enter at bar[i+1] open price".
    """
    out = df_with_dtc[["buy_signal", "sell_signal"]].copy()

    _buy = out["buy_signal"].to_numpy(dtype=bool)
    _sell = out["sell_signal"].to_numpy(dtype=bool)
    
    # Base shifted signals
    shifted_buy = np.concatenate([[False], _buy[:-1]])
    shifted_sell = np.concatenate([[False], _sell[:-1]])

    out["action_buy"] = shifted_buy
    out["action_sell"] = shifted_sell

    return out[["action_buy", "action_sell"]]
