"""
bot6/live_engine.py
===================
Async multi-asset live execution engine for the Bot6 Scanner.

Uses ThreadPoolExecutor to fetch 1-min OHLCV data for all symbols
concurrently, compute DTC signals, and execute orders via the OpenAlgo API.

POLLING CYCLE:
  - Idle (no positions open)      : fetch every 10 seconds
  - Active (positions open)       : fetch every 5 seconds for tighter trail tracking

CONCURRENCY MODEL:
  - ThreadPoolExecutor(max_workers=20) handles concurrent broker API calls
  - Main thread collects all results, then applies state updates sequentially
  - This avoids race conditions on StateManager (which is not thread-safe)

ORDER EXECUTION:
  - Entry / Exit via client.placesmartorder() with product="MIS"
  - Quantity = floor(50_000 / entry_price)
  - Simultaneous positions capped at 10

SAFE ORDERING:
  Each order is placed sequentially after signal collection to avoid
  the OpenAlgo API being hammered with 10 simultaneous order requests.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

# Add root to path
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bot6.data_layer import LiveFeed
from bot6.dtc_indicator import compute_dtc, get_actionable_signals
from bot6.state_manager import StateManager, compute_scanner_quantity
from bot6.position_manager import Side, ExitReason
from bot6.config import (
    WATCHLIST,
    SCANNER_START,
    CUTOFF_TIME,
    SQUARE_OFF_TIME,
    MAX_SIMULTANEOUS_POSITIONS,
)

log = logging.getLogger("Bot6.Live")

# Number of bars to fetch per symbol (enough for EMA-40 warmup + buffer)
LOOKBACK_BARS = 200
POLL_IDLE_SECS = 10
POLL_ACTIVE_SECS = 5
MAX_WORKERS = 20


def _time_str(ts: datetime) -> str:
    return ts.strftime("%H:%M")


def _is_before(ts: datetime, fence: str) -> bool:
    return _time_str(ts) < fence


def _is_after(ts: datetime, fence: str) -> bool:
    return _time_str(ts) >= fence


def _fetch_signal(
    feed: LiveFeed,
    symbol: str,
    lookback: int = LOOKBACK_BARS,
) -> dict | None:
    """
    Worker function: fetch bars for one symbol and return signal dict.
    Returns None on any error (network, missing data, etc.)

    Return dict:
        symbol, action_buy, action_sell, latest_open, latest_high, latest_low, latest_close
    """
    try:
        df = feed.get_bars(symbol, lookback_bars=lookback)
        if df.empty or len(df) < 50:
            return None

        df_dtc = compute_dtc(df)
        signals = get_actionable_signals(df_dtc)

        latest = df.iloc[-1]
        return {
            "symbol": symbol,
            "action_buy": bool(signals["action_buy"].iloc[-1]),
            "action_sell": bool(signals["action_sell"].iloc[-1]),
            "latest_open": float(latest["open"]),
            "latest_high": float(latest["high"]),
            "latest_low": float(latest["low"]),
            "latest_close": float(latest["close"]),
        }
    except Exception as e:
        log.debug(f"Error fetching signal for {symbol}: {e}")
        return None


def run_live(
    api_client,
    watchlist: list[str] | None = None,
    exchange: str = "NSE",
    strategy_name: str = "Bot6_Scanner",
) -> None:
    """
    Main live trading loop. Runs until KeyboardInterrupt.

    Parameters
    ----------
    api_client : openalgo.api instance
        Authenticated OpenAlgo REST client.
    watchlist : list[str] or None
        Symbols to monitor. Defaults to full WATCHLIST.
    exchange : str
        Exchange (default "NSE").
    strategy_name : str
        Strategy name for OpenAlgo order routing.
    """
    if watchlist is None:
        watchlist = WATCHLIST

    state = StateManager()
    feed = LiveFeed(api_client, exchange=exchange)

    log.info(f"[LIVE] Bot6 Scanner started.")
    log.info(f"[LIVE] Watching {len(watchlist)} symbols | Max {MAX_SIMULTANEOUS_POSITIONS} positions")
    log.info(f"[LIVE] Time fences: entry {SCANNER_START} – {CUTOFF_TIME} | square-off {SQUARE_OFF_TIME}")

    while True:
        try:
            now = datetime.now()

            # ----------------------------------------------------------------
            # 1. HARD EOD SQUARE-OFF
            # ----------------------------------------------------------------
            if _is_after(now, SQUARE_OFF_TIME):
                if state.open_count > 0:
                    log.info(f"[LIVE] {SQUARE_OFF_TIME} reached. Squaring off all {state.open_count} positions...")
                    for sym, pos in list(state.active_positions.items()):
                        _place_exit_order(api_client, pos, sym, exchange, strategy_name, "EOD_SQUAREOFF")
                        state._close(
                            sym, pos, pos.entry_price,
                            ExitReason.EOD_SQUAREOFF,
                            pd.Timestamp(now)
                        )
                else:
                    log.info(f"[LIVE] Market closed. Sleeping 60s...")
                time.sleep(60)
                continue

            # ----------------------------------------------------------------
            # 2. CONCURRENT DATA FETCH — all symbols simultaneously
            # ----------------------------------------------------------------
            log.debug(f"[LIVE] Polling {len(watchlist)} symbols...")
            fetch_results: list[dict] = []

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(_fetch_signal, feed, sym): sym
                    for sym in watchlist
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result:
                        fetch_results.append(result)

            # ----------------------------------------------------------------
            # 3. UPDATE OPEN POSITIONS (trail + exits)
            # ----------------------------------------------------------------
            if state.open_count > 0:
                bars_now = {
                    r["symbol"]: (
                        r["latest_open"],
                        r["latest_high"],
                        r["latest_low"],
                        r["latest_close"],
                    )
                    for r in fetch_results
                }
                newly_closed = state.update_all(bars_now, pd.Timestamp(now))

                # Place exit orders for positions closed by trail/target
                for trade in newly_closed:
                    sym = trade["symbol"]
                    reason = trade["exit_reason"]
                    # Position was already removed from state; we need to send the order
                    # The exit price is already computed — place market order
                    log.info(
                        f"[LIVE] {sym} exit triggered: {reason} "
                        f"@ ≈{trade['exit_price']:.2f} | PnL={trade['gross_pnl']:+.2f}"
                    )
                    # Determine direction: if it was LONG, exit is SELL
                    action = "SELL" if trade["side"] == "LONG" else "BUY"
                    try:
                        resp = api_client.placesmartorder(
                            strategy=strategy_name,
                            symbol=sym,
                            action=action,
                            exchange=exchange,
                            price_type="MARKET",
                            product="MIS",
                            quantity=trade["qty"],
                            position_size=0,  # 0 = fully close
                        )
                        log.info(f"[LIVE] Exit order placed for {sym}: {resp}")
                    except Exception as e:
                        log.error(f"[LIVE] Failed to place exit order for {sym}: {e}")

            # ----------------------------------------------------------------
            # 4. ENTRY SCANNING (only within time fences)
            # ----------------------------------------------------------------
            if _is_before(now, SCANNER_START) or _is_after(now, CUTOFF_TIME):
                poll = POLL_ACTIVE_SECS if state.open_count > 0 else POLL_IDLE_SECS
                time.sleep(poll)
                continue

            if state.open_count < MAX_SIMULTANEOUS_POSITIONS:
                for r in fetch_results:
                    sym = r["symbol"]
                    if not state.can_enter(sym):
                        continue

                    entry_price = r["latest_open"]
                    qty = compute_scanner_quantity(entry_price)

                    if r["action_buy"] and not r["action_sell"]:
                        log.info(
                            f"[{now.strftime('%H:%M:%S')}] [SCANNER] {sym} triggered LONG. Executing..."
                        )
                        try:
                            resp = api_client.placesmartorder(
                                strategy=strategy_name,
                                symbol=sym,
                                action="BUY",
                                exchange=exchange,
                                price_type="MARKET",
                                product="MIS",
                                quantity=qty,
                                position_size=qty,
                            )
                            log.info(f"[LIVE] BUY order for {sym}: {resp}")
                            state.enter(sym, Side.LONG, entry_price, qty, pd.Timestamp(now))
                        except Exception as e:
                            log.error(f"[LIVE] BUY order failed for {sym}: {e}")

                    elif r["action_sell"] and not r["action_buy"]:
                        log.info(
                            f"[{now.strftime('%H:%M:%S')}] [SCANNER] {sym} triggered SHORT. Executing..."
                        )
                        try:
                            resp = api_client.placesmartorder(
                                strategy=strategy_name,
                                symbol=sym,
                                action="SELL",
                                exchange=exchange,
                                price_type="MARKET",
                                product="MIS",
                                quantity=qty,
                                position_size=qty * -1,
                            )
                            log.info(f"[LIVE] SELL order for {sym}: {resp}")
                            state.enter(sym, Side.SHORT, entry_price, qty, pd.Timestamp(now))
                        except Exception as e:
                            log.error(f"[LIVE] SELL order failed for {sym}: {e}")

                    # Re-check cap after each entry
                    if state.open_count >= MAX_SIMULTANEOUS_POSITIONS:
                        break

            # ----------------------------------------------------------------
            # 5. SLEEP — tighter interval when positions are open
            # ----------------------------------------------------------------
            poll = POLL_ACTIVE_SECS if state.open_count > 0 else POLL_IDLE_SECS
            log.debug(f"[LIVE] {state.open_count} position(s) open. Sleeping {poll}s...")
            time.sleep(poll)

        except KeyboardInterrupt:
            log.info("[LIVE] Scanner stopped by user (Ctrl+C).")
            break
        except Exception as e:
            log.error(f"[LIVE] Unexpected error in main loop: {e}")
            time.sleep(10)


def _place_exit_order(api_client, pos, symbol: str, exchange: str, strategy_name: str, reason: str) -> None:
    """Helper to place a market exit order for a position."""
    action = "SELL" if pos.side == Side.LONG else "BUY"
    try:
        resp = api_client.placesmartorder(
            strategy=strategy_name,
            symbol=symbol,
            action=action,
            exchange=exchange,
            price_type="MARKET",
            product="MIS",
            quantity=pos.qty,
            position_size=0,
        )
        log.info(f"[LIVE] {reason} exit order for {symbol}: {resp}")
    except Exception as e:
        log.error(f"[LIVE] Exit order failed for {symbol}: {e}")
