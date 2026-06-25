"""
bot6b/report.py
==============
PnL reporting for the Bot6bbb Multi-Asset Scanner.

Takes the list of closed trade dicts from StateManager and prints
a comprehensive backtest report to the terminal, including:
  - Summary statistics (Win Rate, Net PnL, Avg Trade)
  - Max Drawdown (equity curve based)
  - Best / Worst trade
  - Per-symbol breakdown table
  - Exit reason breakdown
"""

from __future__ import annotations

import math
from datetime import date
from typing import Optional

import pandas as pd


def generate_report(trades: list[dict], initial_capital: float = 500_000.0) -> None:
    """
    Print a full backtest PnL report to the terminal.

    Parameters
    ----------
    trades : list[dict]
        Each dict must have: symbol, side, entry_price, exit_price, qty,
        gross_pnl, exit_reason, entry_time, exit_time, date
    initial_capital : float
        Total starting capital (used for return-on-capital calculation)
    """
    if not trades:
        print("\n" + "=" * 65)
        print("  BOT 6 SCANNER — BACKTEST REPORT")
        print("=" * 65)
        print("  No trades were executed in the backtest period.")
        print("=" * 65)
        return

    df = pd.DataFrame(trades)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["date"] = pd.to_datetime(df["date"])

    total_trades = len(df)
    winners = df[df["gross_pnl"] > 0]
    losers = df[df["gross_pnl"] < 0]
    breakeven = df[df["gross_pnl"] == 0]

    win_count = len(winners)
    loss_count = len(losers)
    be_count = len(breakeven)

    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0
    net_pnl = df["gross_pnl"].sum()
    avg_win = winners["gross_pnl"].mean() if len(winners) > 0 else 0.0
    avg_loss = losers["gross_pnl"].mean() if len(losers) > 0 else 0.0
    avg_trade = df["gross_pnl"].mean()
    profit_factor = (
        abs(winners["gross_pnl"].sum() / losers["gross_pnl"].sum())
        if len(losers) > 0 and losers["gross_pnl"].sum() != 0
        else float("inf")
    )

    # ------------------------------------------------------------------ #
    # Max Drawdown (equity curve)
    # ------------------------------------------------------------------ #
    equity_curve = df.sort_values("exit_time")["gross_pnl"].cumsum()
    running_max = equity_curve.cummax()
    drawdown_series = equity_curve - running_max
    max_drawdown = drawdown_series.min()

    # ------------------------------------------------------------------ #
    # Best / Worst trades
    # ------------------------------------------------------------------ #
    best_trade = df.loc[df["gross_pnl"].idxmax()]
    worst_trade = df.loc[df["gross_pnl"].idxmin()]

    # ------------------------------------------------------------------ #
    # Per-symbol breakdown
    # ------------------------------------------------------------------ #
    sym_summary = (
        df.groupby("symbol")
        .agg(
            trades=("gross_pnl", "count"),
            net_pnl=("gross_pnl", "sum"),
            win_rate=("gross_pnl", lambda x: (x > 0).mean() * 100),
        )
        .sort_values("net_pnl", ascending=False)
    )

    # ------------------------------------------------------------------ #
    # Exit reason breakdown
    # ------------------------------------------------------------------ #
    exit_summary = df["exit_reason"].value_counts()

    # ------------------------------------------------------------------ #
    # Date range
    # ------------------------------------------------------------------ #
    start_date = df["date"].min().strftime("%Y-%m-%d")
    end_date = df["date"].max().strftime("%Y-%m-%d")
    unique_days = df["date"].nunique()
    unique_symbols = df["symbol"].nunique()

    # ------------------------------------------------------------------ #
    # PRINT REPORT
    # ------------------------------------------------------------------ #
    sep = "=" * 65
    thin = "-" * 65

    print(f"\n{sep}")
    print(f"  BOT 6 SCANNER — BACKTEST REPORT")
    print(f"  Period : {start_date}  →  {end_date}  ({unique_days} trading days)")
    print(f"  Universe: {unique_symbols} symbols traded")
    print(sep)

    print(f"\n{'SUMMARY':}")
    print(thin)
    print(f"  Total Trades       : {total_trades:>10,}")
    print(f"  Winners            : {win_count:>10,}   ({win_rate:.1f}%)")
    print(f"  Losers             : {loss_count:>10,}")
    print(f"  Breakeven          : {be_count:>10,}")
    print(thin)
    print(f"  Net PnL            : ₹{net_pnl:>12,.2f}")
    print(f"  Avg Win            : ₹{avg_win:>12,.2f}")
    print(f"  Avg Loss           : ₹{avg_loss:>12,.2f}")
    print(f"  Avg Trade          : ₹{avg_trade:>12,.2f}")
    print(f"  Profit Factor      : {profit_factor:>12.2f}x")
    print(f"  Max Drawdown       : ₹{max_drawdown:>12,.2f}")
    print(f"  Return on Capital  : {(net_pnl / initial_capital * 100):>11.2f}%")
    print(thin)

    print(f"\nBEST TRADE:  {best_trade['symbol']} {best_trade['side']} "
          f"on {str(best_trade['date'])[:10]}  →  ₹{best_trade['gross_pnl']:+,.2f}")
    print(f"WORST TRADE: {worst_trade['symbol']} {worst_trade['side']} "
          f"on {str(worst_trade['date'])[:10]}  →  ₹{worst_trade['gross_pnl']:+,.2f}")

    print(f"\nEXIT REASONS:")
    print(thin)
    for reason, count in exit_summary.items():
        pct = count / total_trades * 100
        reason_pnl = df[df["exit_reason"] == reason]["gross_pnl"].sum()
        print(f"  {reason:<25} : {count:>5,} trades  ({pct:5.1f}%)  PnL=₹{reason_pnl:>10,.2f}")

    print(f"\nPER-SYMBOL BREAKDOWN (top 20 by PnL):")
    print(thin)
    print(f"  {'Symbol':<15} {'Trades':>7} {'Net PnL':>12} {'Win%':>8}")
    print(thin)
    for sym, row in sym_summary.head(20).iterrows():
        pnl_str = f"₹{row['net_pnl']:>10,.2f}"
        print(f"  {sym:<15} {int(row['trades']):>7} {pnl_str:>12} {row['win_rate']:>7.1f}%")
    if len(sym_summary) > 20:
        print(f"  ... and {len(sym_summary) - 20} more symbols")

    print(f"\n{sep}\n")


def export_trades_csv(trades: list[dict], filepath: str = "scanner_backtest_trades.csv") -> None:
    """Export all closed trades to a CSV file for further analysis."""
    if not trades:
        print(f"No trades to export.")
        return
    df = pd.DataFrame(trades)
    df.to_csv(filepath, index=False)
    print(f"[REPORT] Trades exported to: {filepath}")
