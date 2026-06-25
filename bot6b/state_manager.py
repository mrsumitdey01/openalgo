"""
bot6b/state_manager.py
=====================
Multi-position state manager for the Bot6bbb Scanner.

Tracks up to MAX_SIMULTANEOUS_POSITIONS open positions simultaneously,
one per symbol. Provides a clean API for:
  - Entering new positions (with cap enforcement)
  - Updating trailing stops for all open positions
  - Checking exit conditions for all open positions
  - Recording closed trades for PnL reporting

Usage
-----
    sm = StateManager()
    if sm.can_enter("INFY"):
        sm.enter("INFY", Side.LONG, entry_price=1800.0, qty=27, ts=pd.Timestamp("..."))
    closed = sm.update_all(bars_by_symbol)   # returns list of newly closed trades
"""

from __future__ import annotations

import math
import logging
from typing import Optional

import pandas as pd

from bot6b.position_manager import Position, Side, ExitReason
from bot6b.config import (
    MAX_SIMULTANEOUS_POSITIONS,
    CAPITAL_PER_TRADE_SCANNER,
    TARGET_PCT,
    INITIAL_SL_PCT,
)

log = logging.getLogger("Bot6bbb.Scanner")


def compute_scanner_quantity(entry_price: float, capital_per_trade: float) -> int:
    """
    Scanner position sizing:
        Qty = floor(capital_per_trade / entry_price)

    Ensures at least 1 share.
    """
    if entry_price <= 0:
        raise ValueError(f"Invalid entry price: {entry_price}")
    return max(math.floor(capital_per_trade / entry_price), 1)


class StateManager:
    """
    Manages the collection of open Bot6bbb positions across all symbols.

    Attributes
    ----------
    active_positions : dict[str, Position]
        Maps symbol → open Position object.
    closed_trades : list[dict]
        Accumulated record of every completed trade.
    """

    def __init__(self):
        self.active_positions: dict[str, Position] = {}
        self.closed_trades: list[dict] = []

    # ------------------------------------------------------------------ #
    # Entry
    # ------------------------------------------------------------------ #

    def can_enter(self, symbol: str) -> bool:
        """
        Returns True if:
          1. Symbol has no currently open position.
          2. Total open positions < MAX_SIMULTANEOUS_POSITIONS.
        """
        if symbol in self.active_positions:
            return False
        if len(self.active_positions) >= MAX_SIMULTANEOUS_POSITIONS:
            return False
        return True

    def enter(
        self,
        symbol: str,
        side: Side,
        entry_price: float,
        qty: int,
        ts: pd.Timestamp,
    ) -> Position:
        """
        Open a new position. Caller must have checked can_enter() first.

        Returns the newly created Position object.
        """
        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            qty=qty,
            entry_time=ts,
        )
        self.active_positions[symbol] = pos
        log.info(
            f"[{ts.strftime('%H:%M:%S')}] [SCANNER] {symbol} triggered "
            f"{'LONG' if side == Side.LONG else 'SHORT'}. Executing... "
            f"Entry={entry_price:.2f} Qty={qty} "
            f"SL={pos.initial_sl:.2f} TP={pos.target:.2f} "
            f"[{len(self.active_positions)}/{MAX_SIMULTANEOUS_POSITIONS} positions open]"
        )
        return pos

    # ------------------------------------------------------------------ #
    # Bar-by-bar Update
    # ------------------------------------------------------------------ #

    def update_all(
        self,
        bars_by_symbol: dict[str, tuple[float, float, float, float]],
        current_ts: pd.Timestamp,
    ) -> list[dict]:
        """
        Process one bar for every open position.

        Parameters
        ----------
        bars_by_symbol : dict[str, (open, high, low, close)]
            OHLC values for the current bar, keyed by symbol.
        current_ts : pd.Timestamp
            Timestamp of the current bar.

        Returns
        -------
        list[dict]
            Newly closed trade records in this bar (may be empty).
        """
        newly_closed: list[dict] = []
        # Snapshot keys to avoid mutating dict during iteration
        for symbol in list(self.active_positions.keys()):
            pos = self.active_positions[symbol]
            if symbol not in bars_by_symbol:
                continue  # No data for this symbol on this bar

            bar_open, bar_high, bar_low, bar_close = bars_by_symbol[symbol]

            # Step 1: Update trail
            pos.update_trail(bar_high, bar_low)

            # Step 2: Check exit
            exit_result = pos.check_exit(bar_high, bar_low, bar_close)
            if exit_result:
                exit_px, reason = exit_result
                trade = self._close(symbol, pos, exit_px, reason, current_ts)
                newly_closed.append(trade)

        return newly_closed

    def eod_squareoff(
        self,
        bars_by_symbol: dict[str, tuple[float, float, float, float]],
        current_ts: pd.Timestamp,
    ) -> list[dict]:
        """
        Force-close ALL open positions at current bar's open price (market order).
        Called at SQUARE_OFF_TIME (15:15 IST).
        """
        closed: list[dict] = []
        for symbol in list(self.active_positions.keys()):
            pos = self.active_positions[symbol]
            if symbol in bars_by_symbol:
                exit_px = bars_by_symbol[symbol][0]  # Use bar open as fill
            else:
                exit_px = pos.entry_price  # Fallback
            trade = self._close(symbol, pos, exit_px, ExitReason.EOD_SQUAREOFF, current_ts)
            closed.append(trade)
            log.info(
                f"[{current_ts.strftime('%H:%M:%S')}] [SCANNER] EOD SQUAREOFF "
                f"{symbol} {pos.side.name} @ {exit_px:.2f}"
            )
        return closed

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _close(
        self,
        symbol: str,
        pos: Position,
        exit_price: float,
        reason: ExitReason,
        exit_ts: pd.Timestamp,
    ) -> dict:
        gross_pnl = (exit_price - pos.entry_price) * pos.qty * (
            1 if pos.side == Side.LONG else -1
        )
        trade = {
            "date": pos.entry_time.date(),
            "symbol": symbol,
            "side": pos.side.name,
            "entry_time": pos.entry_time,
            "entry_price": round(pos.entry_price, 2),
            "exit_time": exit_ts,
            "exit_price": round(exit_price, 2),
            "qty": pos.qty,
            "gross_pnl": round(gross_pnl, 2),
            "exit_reason": reason.value,
            "initial_sl": round(pos.initial_sl, 2),
            "target": round(pos.target, 2),
            "peak_price": round(pos.peak_price, 2),
            "capital_deployed": round(pos.entry_price * pos.qty, 2),
        }
        self.closed_trades.append(trade)
        pos.close()
        del self.active_positions[symbol]

        pnl_sign = "+" if gross_pnl >= 0 else ""
        log.info(
            f"[{exit_ts.strftime('%H:%M:%S')}] [EXIT] {symbol} {pos.side.name} "
            f"@ {exit_price:.2f} | PnL={pnl_sign}{gross_pnl:.2f} | "
            f"Reason={reason.value} | "
            f"[{len(self.active_positions)}/{MAX_SIMULTANEOUS_POSITIONS} positions open]"
        )
        return trade

    # ------------------------------------------------------------------ #
    # Info
    # ------------------------------------------------------------------ #

    @property
    def open_count(self) -> int:
        return len(self.active_positions)

    def summary(self) -> str:
        lines = [f"Active Positions ({self.open_count}/{MAX_SIMULTANEOUS_POSITIONS}):"]
        for sym, pos in self.active_positions.items():
            lines.append(f"  {repr(pos)}")
        return "\n".join(lines)
