"""
bot6/backtest_runner.py
=======================
Backtesting harness for Bot6 DTC Intraday Strategy.

Feeds historical 1-minute OHLCV data through the execution engine
and produces a full performance report with zero simulation bias.

HOW TO RUN:
    1. Place your 1-min CSV data in the bot6/ directory.
       Expected format:
         datetime,open,high,low,close,volume
         2025-01-02 09:15:00,2950.00,2952.50,2948.00,2951.00,150000
         ...
    2. Run: python backtest_runner.py --symbol RELIANCE --file reliance_1min.csv

    Or use the programmatic API:
        from backtest_runner import run_backtest
        results = run_backtest("RELIANCE", df_ohlcv)
        print(results['summary'])
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from execution_engine import Bot6Engine
from config import TRADE_CSV


# --------------------------------------------------------------------------- #
# SYNTHETIC DATA GENERATOR (for self-testing without real data)
# --------------------------------------------------------------------------- #
def generate_sample_data(
    start: str = "2025-01-02 09:15:00",
    end: str = "2025-01-02 15:30:00",
    base_price: float = 2500.0,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate a synthetic 1-minute OHLCV DataFrame for testing.
    Simulates realistic intraday price action with momentum regimes.
    """
    np.random.seed(seed)
    idx = pd.date_range(start=start, end=end, freq="1min")
    n = len(idx)

    # Random walk with momentum bias
    returns = np.random.normal(0, 0.0008, n)
    # Inject a bullish trend from 09:45 to 11:00 and bearish from 13:00 to 14:00
    for i, ts in enumerate(idx):
        if ts.hour == 9 and ts.minute >= 45:
            returns[i] += 0.0004
        elif ts.hour == 10 and ts.minute <= 30:
            returns[i] += 0.0004
        elif ts.hour == 13:
            returns[i] -= 0.0004
        elif ts.hour == 14 and ts.minute <= 30:
            returns[i] -= 0.0003

    prices = base_price * np.exp(np.cumsum(returns))

    # Construct OHLC from close prices
    opens = np.roll(prices, 1)
    opens[0] = base_price

    hi_lo_spread = np.random.uniform(0.001, 0.004, n)
    highs = np.maximum(prices, opens) * (1 + hi_lo_spread)
    lows = np.minimum(prices, opens) * (1 - hi_lo_spread)

    df = pd.DataFrame(
        {
            "open": np.round(opens, 2),
            "high": np.round(highs, 2),
            "low": np.round(lows, 2),
            "close": np.round(prices, 2),
            "volume": np.random.randint(10000, 500000, n),
        },
        index=idx,
    )
    return df


# --------------------------------------------------------------------------- #
# PERFORMANCE SUMMARY
# --------------------------------------------------------------------------- #
def compute_summary(trades: list[dict]) -> dict:
    """Compute key performance metrics from trade list."""
    if not trades:
        return {"total_trades": 0, "message": "No trades executed."}

    df = pd.DataFrame(trades)
    total_pnl = df["gross_pnl"].sum()
    winning = df[df["gross_pnl"] > 0]
    losing = df[df["gross_pnl"] <= 0]

    win_rate = len(winning) / len(df) * 100 if len(df) > 0 else 0
    avg_win = winning["gross_pnl"].mean() if len(winning) > 0 else 0
    avg_loss = losing["gross_pnl"].mean() if len(losing) > 0 else 0
    profit_factor = (
        winning["gross_pnl"].sum() / abs(losing["gross_pnl"].sum())
        if len(losing) > 0 and losing["gross_pnl"].sum() != 0
        else float("inf")
    )
    max_drawdown = df["gross_pnl"].cumsum().cummax() - df["gross_pnl"].cumsum()
    max_dd = max_drawdown.max()

    exit_counts = df["exit_reason"].value_counts().to_dict()

    return {
        "total_trades": len(df),
        "total_pnl": round(total_pnl, 2),
        "win_rate_pct": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown": round(max_dd, 2),
        "exit_breakdown": exit_counts,
        "long_trades": len(df[df["side"] == "LONG"]),
        "short_trades": len(df[df["side"] == "SHORT"]),
    }


def print_summary(summary: dict, symbol: str) -> None:
    """Print a formatted performance summary."""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  BOT6 DTC BACKTEST RESULTS - {symbol}")
    print(sep)
    if "message" in summary:
        print(f"  {summary['message']}")
        return
    print(f"  Total Trades   : {summary['total_trades']}")
    print(f"  Total PnL      : Rs.{summary['total_pnl']:+,.2f}")
    print(f"  Win Rate       : {summary['win_rate_pct']}%")
    print(f"  Avg Win        : Rs.{summary['avg_win']:+,.2f}")
    print(f"  Avg Loss       : Rs.{summary['avg_loss']:+,.2f}")
    print(f"  Profit Factor  : {summary['profit_factor']:.2f}x")
    print(f"  Max Drawdown   : Rs.{summary['max_drawdown']:,.2f}")
    print(f"  Long Trades    : {summary['long_trades']}")
    print(f"  Short Trades   : {summary['short_trades']}")
    print(f"\n  Exit Breakdown:")
    for reason, count in summary.get("exit_breakdown", {}).items():
        print(f"    {reason:<25}: {count}")
    print(f"\n  Trade log saved to: {TRADE_CSV}")
    print(sep + "\n")


# --------------------------------------------------------------------------- #
# PROGRAMMATIC API
# --------------------------------------------------------------------------- #
def run_backtest(symbol: str, df: pd.DataFrame) -> dict:
    """
    Run Bot6 backtest on a given OHLCV DataFrame.

    Parameters
    ----------
    symbol : str
        Stock symbol string (used in logging and output)
    df : pd.DataFrame
        1-minute OHLCV with DatetimeIndex

    Returns
    -------
    dict with keys: 'trades', 'summary'
    """
    engine = Bot6Engine(symbol=symbol)
    trades = engine.run(df)
    summary = compute_summary(trades)
    print_summary(summary, symbol)
    return {"trades": trades, "summary": summary}


# --------------------------------------------------------------------------- #
# CLI ENTRY POINT
# --------------------------------------------------------------------------- #
def _load_csv(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(
        filepath,
        parse_dates=["datetime"],
        index_col="datetime",
    )
    df.columns = df.columns.str.lower()
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bot6 DTC Intraday Backtest Runner"
    )
    parser.add_argument(
        "--symbol", type=str, default="SAMPLE", help="Stock symbol"
    )
    parser.add_argument(
        "--file", type=str, default=None,
        help="Path to 1-min OHLCV CSV (datetime,open,high,low,close,volume)"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Run with synthetically generated data (no file needed)"
    )
    args = parser.parse_args()

    if args.demo or args.file is None:
        print("Running with synthetic 1-min data (demo mode)...")
        df = generate_sample_data()
        symbol = args.symbol if args.symbol != "SAMPLE" else "DEMO_STOCK"
    else:
        if not Path(args.file).exists():
            print(f"ERROR: File not found: {args.file}")
            sys.exit(1)
        df = _load_csv(args.file)
        symbol = args.symbol

    run_backtest(symbol, df)


if __name__ == "__main__":
    main()
