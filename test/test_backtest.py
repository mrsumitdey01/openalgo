# test/test_backtest.py
"""
Unit tests for the OpenAlgo Backtest Service
"""

import os
import sys
import pytest
import pandas as pd
import numpy as np

# Ensure root directory is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.backtest_service import (
    calculate_sma,
    calculate_ema,
    calculate_rsi,
    calculate_macd,
    run_backtest
)


def test_calculate_sma():
    prices = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
    sma = calculate_sma(prices, 3)
    assert pd.isna(sma[0])
    assert pd.isna(sma[1])
    assert sma[2] == pytest.approx(12.0)
    assert sma[3] == pytest.approx(14.0)
    assert sma[4] == pytest.approx(16.0)


def test_calculate_ema():
    prices = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
    ema = calculate_ema(prices, 3)
    assert ema[0] == pytest.approx(10.0)
    # multiplier = 2 / (3 + 1) = 0.5
    # ema[1] = 12 * 0.5 + 10 * 0.5 = 11.0
    assert ema[1] == pytest.approx(11.0)
    # ema[2] = 14 * 0.5 + 11 * 0.5 = 12.5
    assert ema[2] == pytest.approx(12.5)


def test_calculate_rsi():
    prices = pd.Series([50.0] * 20)
    rsi = calculate_rsi(prices, 14)
    # Since prices are flat, gain/loss is 0, rs is 0, rsi should be 0.0
    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_calculate_macd():
    prices = pd.Series([10.0] * 50)
    macd_line, signal_line, macd_hist = calculate_macd(prices, 12, 26, 9)
    assert macd_line.iloc[-1] == pytest.approx(0.0)
    assert signal_line.iloc[-1] == pytest.approx(0.0)
    assert macd_hist.iloc[-1] == pytest.approx(0.0)


def test_run_backtest_missing_symbol():
    success, response_data, status_code = run_backtest({})
    assert success is False
    assert status_code == 400
    assert "Symbol is required" in response_data["message"]


def test_run_backtest_invalid_strategy():
    success, response_data, status_code = run_backtest({
        "symbol": "SBIN",
        "strategy": "non_existent_strategy"
    })
    assert success is False
    assert status_code == 400
    assert "Unsupported strategy" in response_data["message"]
