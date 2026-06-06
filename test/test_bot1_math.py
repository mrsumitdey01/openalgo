import sys
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

# Add strategies/scripts directory to sys.path so we can import the strategy module
sys.path.append(str(Path(__file__).parent.parent / "strategies" / "scripts"))

from bot1_hull_dtc_ribbon import HullBBI, DTCRibbon, check_signals, resolve_spread_symbols

def test_hull_bbi_math():
    """Verify that HullBBI computes correct HMA and bullish/bearish indicators."""
    # HMA period is 21, so we create a linear sequence of 40 points to let it warm up
    close_prices = [float(x) for x in range(1, 41)]
    df = pd.DataFrame({"close": close_prices})
    
    bbi = HullBBI(length=21)
    df = bbi.compute(df)
    
    # Check column existence
    assert "hma" in df.columns
    assert "hma_prev" in df.columns
    assert "hma_bullish" in df.columns
    assert "hma_bearish" in df.columns
    
    # Warmup check
    assert pd.isna(df["hma"].iloc[15])
    assert not pd.isna(df["hma"].iloc[-1])
    
    # Direction check (rising sequence should be bullish)
    assert df["hma_bullish"].iloc[-1] == True
    assert df["hma_bearish"].iloc[-1] == False
    assert df["hma_prev"].iloc[-1] == df["hma"].iloc[-2]


def test_dtc_ribbon_math():
    """Verify that DTCRibbon computes the 6 EMAs and strict alignment flags."""
    # Warmup requires at least length 40
    close_prices = [float(x) for x in range(1, 51)]
    df = pd.DataFrame({"close": close_prices})
    
    ribbon = DTCRibbon(lengths=[8, 13, 21, 26, 34, 40])
    df = ribbon.compute(df)
    
    # Check column existence
    for l in [8, 13, 21, 26, 34, 40]:
        assert f"ema_{l}" in df.columns
    assert "ribbon_max" in df.columns
    assert "ribbon_min" in df.columns
    assert "ribbon_bullish" in df.columns
    assert "ribbon_bearish" in df.columns
    
    # In a rising close sequence, EMA 8 > EMA 13 > ... > EMA 40 (bullish ribbon alignment)
    assert df["ribbon_bullish"].iloc[-1] == True
    assert df["ribbon_bearish"].iloc[-1] == False
    assert df["ribbon_max"].iloc[-1] == df["ema_8"].iloc[-1]
    assert df["ribbon_min"].iloc[-1] == df["ema_40"].iloc[-1]


def test_check_signals_logic():
    """Verify that check_signals detects long/short entries and exit conditions correctly."""
    # Signals are checked against df.iloc[-2] (last completed candle)
    # Row 0 will be evaluated since len(df) == 2.
    
    # Case 1: Long Entry (Close > HMA, HMA bullish, Ribbon Bullish)
    df_long = pd.DataFrame({
        "close": [100.0, 105.0],
        "hma": [90.0, 95.0],
        "hma_bullish": [True, True],
        "hma_bearish": [False, False],
        "ribbon_bullish": [True, True],
        "ribbon_bearish": [False, False]
    })
    assert check_signals(df_long, current_position=None) == "LONG"
    
    # Case 2: Short Entry (Close < HMA, HMA bearish, Ribbon Bearish)
    df_short = pd.DataFrame({
        "close": [90.0, 85.0],
        "hma": [100.0, 95.0],
        "hma_bullish": [False, False],
        "hma_bearish": [True, True],
        "ribbon_bullish": [False, False],
        "ribbon_bearish": [True, True]
    })
    assert check_signals(df_short, current_position=None) == "SHORT"
    
    # Case 3: Exit Long (HMA bearish, Close < HMA - 5.0)
    # Row 0: HMA=100.0, HMA_bearish=True, Close=94.0 (< HMA - 5.0) -> Exit Long
    df_exit_long = pd.DataFrame({
        "close": [94.0, 90.0],
        "hma": [100.0, 98.0],
        "hma_bullish": [False, False],
        "hma_bearish": [True, True],
        "ribbon_bullish": [False, False],
        "ribbon_bearish": [False, False]
    })
    assert check_signals(df_exit_long, current_position="LONG") == "EXIT_LONG"
    
    # Case 4: No Exit Long if Close is close to HMA
    # Row 0: HMA=100.0, HMA_bearish=True, Close=98.0 (> HMA - 5.0) -> Hold Long
    df_hold_long = pd.DataFrame({
        "close": [98.0, 97.0],
        "hma": [100.0, 98.0],
        "hma_bullish": [False, False],
        "hma_bearish": [True, True],
        "ribbon_bullish": [False, False],
        "ribbon_bearish": [False, False]
    })
    assert check_signals(df_hold_long, current_position="LONG") is None


def test_option_symbol_formatting():
    """Verify that resolve_spread_symbols maps strikes and formats symbols correctly."""
    # Spot 65435.0, LONG: ATM CE should be 65400, OTM CE should be 65900 (ATM+500)
    atm_ce, otm_ce = resolve_spread_symbols(65435.0, "LONG", "30JUN26")
    assert atm_ce == "BANKNIFTY30JUN2665400CE"
    assert otm_ce == "BANKNIFTY30JUN2665900CE"

    # Spot 65465.0, SHORT: ATM PE should be 65500 (rounded up), OTM PE should be 65000 (ATM-500)
    atm_pe, otm_pe = resolve_spread_symbols(65465.0, "SHORT", "30JUN26")
    assert atm_pe == "BANKNIFTY30JUN2665500PE"
    assert otm_pe == "BANKNIFTY30JUN2665000PE"
