"""
bot6b/backtest_engine.py
=======================
Bar-by-bar backtest engine for the Bot6bbb Multi-Asset Scanner.

DESIGN:
  1. Loads 2 years of 1-min NSE data from DuckDB in a single bulk query.
  2. Pre-computes DTC signals (all 6 EMAs + actionable buy/sell) for every
     symbol using vectorized Pandas operations.
  3. Iterates chronologically across ALL symbols simultaneously, one bar at a time.
  4. Enforces:
     - Time fences (09:30 entry start, 14:45 cutoff, 15:15 hard square-off)
     - 10-position cap
     - 50,000 Rs per trade sizing
     - Anti-lookahead: entry uses NEXT bar's open after signal bar closes

BAR ITERATION STRATEGY:
  Build a unified sorted list of all unique timestamps, then for each
  timestamp, process every symbol that has data at that exact bar.
  This ensures correct chronological ordering and that time fence logic
  is applied consistently across all symbols.

PERFORMANCE:
  With 97 symbols × ~185,000 bars each = ~18M rows, DuckDB handles the
  bulk query efficiently. EMA computation is vectorized (no Python loops
  per bar). Only the state update loop (position tracking) iterates bar-by-bar.
"""

from __future__ import annotations

import logging
import sys
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# Add the openalgo root to path so bot6b imports work
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bot6b.data_layer import DuckDBFeed
from bot6b.dtc_indicator import compute_dtc, get_actionable_signals
from bot6b.state_manager import StateManager, compute_scanner_quantity
from bot6b.position_manager import Side
from bot6b.config import (
    WATCHLIST,
    SCANNER_START,
    CUTOFF_TIME,
    SQUARE_OFF_TIME,
    TOTAL_CAPITAL,
)

log = logging.getLogger("Bot6bbb.Backtest")


def _time_str(ts: pd.Timestamp) -> str:
    return ts.strftime("%H:%M")


def _is_before(ts: pd.Timestamp, fence: str) -> bool:
    return _time_str(ts) < fence


def _is_after(ts: pd.Timestamp, fence: str) -> bool:
    return _time_str(ts) >= fence


def _precompute_signals(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    For each symbol, compute DTC + actionable signals on the full history.

    Returns {symbol: df_with_signals} where df_with_signals has columns:
        open, high, low, close, volume, action_buy, action_sell
    """
    result: dict[str, pd.DataFrame] = {}
    total = len(data)
    log.info(f"[BACKTEST] Pre-computing DTC signals for {total} symbols...")

    for i, (sym, df) in enumerate(data.items(), 1):
        if df.empty or len(df) < 50:
            # Need at least 50 bars for EMA-40 to stabilize
            continue
        try:
            df_dtc = compute_dtc(df)
            signals = get_actionable_signals(df_dtc)
            df_out = df[["open", "high", "low", "close", "volume"]].copy()
            df_out["action_buy"] = signals["action_buy"]
            df_out["action_sell"] = signals["action_sell"]
            result[sym] = df_out
        except Exception as e:
            log.warning(f"  Failed to compute DTC for {sym}: {e}")
            continue

        if i % 20 == 0 or i == total:
            log.info(f"  [{i}/{total}] Signals computed...")

    log.info(f"[BACKTEST] Signals ready for {len(result)} symbols.")
    return result


def run_backtest(
    db_path: str = "db/historify.duckdb",
    symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    total_capital: float = 500000.0,
    capital_per_trade: float = 50000.0,
) -> list[dict]:
    """
    Run the full multi-asset backtest.

    Parameters
    ----------
    db_path : str
        Path to the DuckDB database file.
    symbols : list[str] or None
        Subset of symbols to backtest. Defaults to full WATCHLIST (97 stocks).
    start_date : str or None
        ISO date string like "2024-06-24". Defaults to 2 years ago.
    end_date : str or None
        ISO date string like "2026-06-24". Defaults to today.
    total_capital: float
        Total capital to deploy across all concurrent positions.
    capital_per_trade: float
        Capital allocated to a single position.

    Returns
    -------
    list[dict]
        All closed trade records. Pass to report.generate_report() for output.
    """
    if symbols is None:
        symbols = WATCHLIST

    # ------------------------------------------------------------------
    # 1. Parse date range
    # ------------------------------------------------------------------
    if end_date is None:
        end_dt = pd.Timestamp.now()
    else:
        end_dt = pd.Timestamp(end_date)

    if start_date is None:
        start_dt = end_dt - pd.DateOffset(years=2)
    else:
        start_dt = pd.Timestamp(start_date)

    # Convert to unix timestamps (seconds) — DB stores BIGINT unix seconds in IST
    # IST = UTC+5:30 → subtract 5.5 hours to get UTC, but since timestamps in DB
    # are already unix epoch (absolute), we directly convert.
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    log.info(f"[BACKTEST] Starting backtest: {start_date} → {end_date}")
    log.info(f"[BACKTEST] Universe: {len(symbols)} symbols")
    log.info(f"[BACKTEST] Capital: ₹{total_capital:,.0f} | Max positions: 10 | ₹{capital_per_trade:,.0f}/trade")

    # ------------------------------------------------------------------
    # 2. Load data
    # ------------------------------------------------------------------
    feed = DuckDBFeed(db_path)
    log.info(f"[BACKTEST] Loading data from {db_path}...")
    raw_data = feed.get_all_bars_for_backtest(symbols, start_ts, end_ts)
    log.info(f"[BACKTEST] Loaded data for {len(raw_data)} symbols.")

    if not raw_data:
        log.error("[BACKTEST] No data loaded! Check DB path and symbol names.")
        return []

    # ------------------------------------------------------------------
    # 3. Pre-compute DTC signals for all symbols (vectorized, fast)
    # ------------------------------------------------------------------
    all_signals = _precompute_signals(raw_data)

    # ------------------------------------------------------------------
    # 4. Build unified chronological timestamp index
    # ------------------------------------------------------------------
    log.info("[BACKTEST] Building unified timestamp index and fast lookups...")
    all_timestamps: set[pd.Timestamp] = set()
    all_signals_dict = {}
    for sym, df in all_signals.items():
        all_timestamps.update(df.index.tolist())
        # Convert df to dictionary {Timestamp: row_dict} for O(1) fast lookup
        all_signals_dict[sym] = df.to_dict(orient='index')
        
    sorted_timestamps = sorted(all_timestamps)
    log.info(f"[BACKTEST] Total unique bars to process: {len(sorted_timestamps):,}")

    # ------------------------------------------------------------------
    # 5. Main bar-by-bar simulation loop
    # ------------------------------------------------------------------
    state = StateManager()
    squaredoff_today: set[pd.Timestamp] = set()  # Track per-day square-off

    log.info("[BACKTEST] Starting bar-by-bar simulation...")
    bar_count = 0
    prev_day: pd.Timestamp | None = None

    for ts in sorted_timestamps:
        bar_count += 1
        if bar_count % 100_000 == 0:
            log.info(
                f"  Progress: {bar_count:,}/{len(sorted_timestamps):,} bars | "
                f"Open positions: {state.open_count} | "
                f"Trades closed: {len(state.closed_trades)}"
            )

        current_day = ts.date()

        # ----------------------------------------------------------------
        # 5a. Hard EOD square-off at 15:15
        # ----------------------------------------------------------------
        if _is_after(ts, SQUARE_OFF_TIME):
            if state.open_count > 0 and current_day not in squaredoff_today:
                bars_now = _get_bars_at(all_signals_dict, state.active_positions.keys(), ts)
                state.eod_squareoff(bars_now, ts)
                squaredoff_today.add(current_day)
            continue

        # ----------------------------------------------------------------
        # 5b. Build OHLC snapshot for current bar
        # ----------------------------------------------------------------
        bars_now = _get_bars_at(all_signals_dict, all_signals_dict.keys(), ts)

        # ----------------------------------------------------------------
        # 5c. Update open positions — trail + exit checks
        # ----------------------------------------------------------------
        if state.open_count > 0:
            state.update_all(bars_now, ts)

        # ----------------------------------------------------------------
        # 5d. Entry scanning (only within time fences)
        # ----------------------------------------------------------------
        if _is_before(ts, SCANNER_START) or _is_after(ts, CUTOFF_TIME):
            continue

        if state.open_count >= 10:
            continue

        # Scan each symbol for entry signals
        for sym, records in all_signals_dict.items():
            row = records.get(ts)
            if row is None:
                continue
            if not state.can_enter(sym):
                continue

            action_buy = bool(row["action_buy"])
            action_sell = bool(row["action_sell"])

            if action_buy and not action_sell:
                entry_price = float(row["open"])
                qty = compute_scanner_quantity(entry_price, capital_per_trade)
                state.enter(sym, Side.LONG, entry_price, qty, ts)

            elif action_sell and not action_buy:
                entry_price = float(row["open"])
                qty = compute_scanner_quantity(entry_price, capital_per_trade)
                state.enter(sym, Side.SHORT, entry_price, qty, ts)

    # ------------------------------------------------------------------
    # 6. Force-close any remaining open positions (if data ends mid-day)
    # ------------------------------------------------------------------
    if state.open_count > 0:
        log.warning(
            f"[BACKTEST] {state.open_count} positions still open at end of data. "
            "Force-closing at last known price."
        )
        # Build final bars from last available timestamp
        last_ts = sorted_timestamps[-1]
        last_bars = _get_bars_at(all_signals, state.active_positions.keys(), last_ts)
        state.eod_squareoff(last_bars, last_ts)

    log.info(
        f"[BACKTEST] Done. Bars processed: {bar_count:,} | "
        f"Total trades: {len(state.closed_trades)}"
    )
    return state.closed_trades


def _get_bars_at(
    all_signals_dict: dict[str, dict],
    symbols,
    ts: pd.Timestamp,
) -> dict[str, tuple[float, float, float, float]]:
    """
    For each symbol in `symbols`, extract (open, high, low, close) at `ts`.
    Returns only symbols that have data at exactly this timestamp.
    """
    result: dict[str, tuple[float, float, float, float]] = {}
    for sym in symbols:
        records = all_signals_dict.get(sym)
        if records is None:
            continue
        row = records.get(ts)
        if row is None:
            continue
        result[sym] = (
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
        )
    return result
