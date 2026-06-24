"""
bot6/execution_engine.py
========================
Main event-driven execution loop for Bot6 DTC Intraday Strategy.

DESIGN PRINCIPLES:
    1. Processes each 1-minute bar sequentially — purely procedural.
    2. Never looks at the current bar's close for entry decisions.
       Entries are triggered by PREVIOUS bar's signal (action_buy/action_sell).
    3. Within each bar: update trail first, then check exits, then check entries.
    4. Time fences are enforced strictly using the bar's timestamp.
    5. EOD square-off at 15:15 IST is a hard market order — no conditions.

STATE MACHINE per session:
    IDLE → signal fires → ENTERED → exit condition → IDLE
    (one position at a time; no pyramiding)
"""

from __future__ import annotations
import logging
import csv
from pathlib import Path
from typing import Optional

import pandas as pd

from dtc_indicator import compute_dtc, get_actionable_signals
from position_manager import Position, Side, ExitReason, compute_quantity
from config import (
    MARKET_START,
    CUTOFF_TIME,
    SQUARE_OFF_TIME,
    LOG_FILE,
    TRADE_CSV,
)

# --------------------------------------------------------------------------- #
# LOGGING SETUP
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("Bot6")


def _time_str(ts: pd.Timestamp) -> str:
    """Return HH:MM string from a Timestamp."""
    return ts.strftime("%H:%M")


def _is_before(ts: pd.Timestamp, fence: str) -> bool:
    t = _time_str(ts)
    return t < fence


def _is_after(ts: pd.Timestamp, fence: str) -> bool:
    t = _time_str(ts)
    return t >= fence


# --------------------------------------------------------------------------- #
# TRADE LOG CSV
# --------------------------------------------------------------------------- #
TRADE_CSV_HEADERS = [
    "date", "symbol", "side", "entry_time", "entry_price",
    "exit_time", "exit_price", "qty",
    "gross_pnl", "exit_reason",
    "initial_sl", "target", "peak_price",
]


def _init_csv(path: str) -> None:
    p = Path(path)
    if not p.exists():
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TRADE_CSV_HEADERS)
            writer.writeheader()


def _log_trade(
    pos: Position,
    exit_time: pd.Timestamp,
    exit_price: float,
    exit_reason: ExitReason,
) -> None:
    gross_pnl = (exit_price - pos.entry_price) * pos.qty * (
        1 if pos.side == Side.LONG else -1
    )
    row = {
        "date": pos.entry_time.date(),
        "symbol": pos.symbol,
        "side": pos.side.name,
        "entry_time": pos.entry_time.strftime("%H:%M:%S"),
        "entry_price": round(pos.entry_price, 2),
        "exit_time": exit_time.strftime("%H:%M:%S"),
        "exit_price": round(exit_price, 2),
        "qty": pos.qty,
        "gross_pnl": round(gross_pnl, 2),
        "exit_reason": exit_reason.value,
        "initial_sl": round(pos.initial_sl, 2),
        "target": round(pos.target, 2),
        "peak_price": round(pos.peak_price, 2),
    }
    with open(TRADE_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_CSV_HEADERS)
        writer.writerow(row)
    log.info(
        f"TRADE CLOSED | {pos.symbol} {pos.side.name} x{pos.qty} | "
        f"Entry={pos.entry_price:.2f} Exit={exit_price:.2f} | "
        f"PnL={gross_pnl:+.2f} | Reason={exit_reason.value}"
    )


# --------------------------------------------------------------------------- #
# MAIN EXECUTION ENGINE
# --------------------------------------------------------------------------- #
class Bot6Engine:
    """
    Event-driven bar processor for Bot6.

    Usage
    -----
    engine = Bot6Engine(symbol="RELIANCE")
    results = engine.run(df_ohlcv)  # returns full trade log as list of dicts
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.position: Optional[Position] = None
        self.trades: list[dict] = []
        _init_csv(TRADE_CSV)

    def run(self, df: pd.DataFrame) -> list[dict]:
        """
        Process all bars in df sequentially.

        Parameters
        ----------
        df : pd.DataFrame
            1-minute OHLCV, DatetimeIndex (IST), columns: open, high, low, close, volume

        Returns
        -------
        list of trade dictionaries (same data as written to CSV)
        """
        # --- Step 1: Compute DTC ribbon on the full dataset ---
        df_dtc = compute_dtc(df)
        signals = get_actionable_signals(df_dtc)

        # Merge action columns into working dataframe
        df_work = df_dtc.copy()
        df_work["action_buy"] = signals["action_buy"]
        df_work["action_sell"] = signals["action_sell"]

        log.info(f"Bot6 started for {self.symbol} | Bars: {len(df_work)}")

        # --- Step 2: Process bar by bar ---
        for ts, bar in df_work.iterrows():
            self._process_bar(ts, bar)

        log.info(f"Bot6 finished for {self.symbol} | Trades: {len(self.trades)}")
        return self.trades

    def _process_bar(self, ts: pd.Timestamp, bar: pd.Series) -> None:
        """
        Process a single 1-minute bar. Sequence within each bar:
            1. Hard square-off check (15:15)
            2. Update trailing stop (if in position)
            3. Check exit conditions (target / trail SL / initial SL)
            4. Check for new entry signals (only if no open position)
        """
        bar_open = bar["open"]
        bar_high = bar["high"]
        bar_low = bar["low"]
        bar_close = bar["close"]

        # ------------------------------------------------------------------ #
        # 1. HARD SQUARE-OFF at 15:15 IST
        # ------------------------------------------------------------------ #
        if _is_after(ts, SQUARE_OFF_TIME):
            if self.position and self.position.is_open:
                # Market order at bar open (best approximation)
                exit_px = bar_open
                self._exit_position(ts, exit_px, ExitReason.EOD_SQUAREOFF)
            return  # No further action after square-off time

        # ------------------------------------------------------------------ #
        # 2. UPDATE TRAILING STOP (before checking exits)
        # ------------------------------------------------------------------ #
        if self.position and self.position.is_open:
            self.position.update_trail(bar_high, bar_low)

        # ------------------------------------------------------------------ #
        # 3. CHECK EXIT CONDITIONS
        # ------------------------------------------------------------------ #
        if self.position and self.position.is_open:
            exit_result = self.position.check_exit(bar_high, bar_low, bar_close)
            if exit_result:
                exit_px, reason = exit_result
                self._exit_position(ts, exit_px, reason)
                # After exiting, do not enter on same bar
                return

        # ------------------------------------------------------------------ #
        # 4. CHECK ENTRY CONDITIONS
        # ------------------------------------------------------------------ #
        # Skip entries before market start
        if _is_before(ts, MARKET_START):
            return

        # Skip new entries after cutoff time
        if _is_after(ts, CUTOFF_TIME):
            return

        # Only one position at a time
        if self.position and self.position.is_open:
            return

        # Entry execution: action_buy/sell = signal from PREVIOUS bar
        # Entry price = current bar OPEN (realistic fill)
        if bar["action_buy"] and not bar["action_sell"]:
            entry_px = bar_open
            qty = compute_quantity(entry_px)
            self._enter_position(ts, Side.LONG, entry_px, qty)

        elif bar["action_sell"] and not bar["action_buy"]:
            entry_px = bar_open
            qty = compute_quantity(entry_px)
            self._enter_position(ts, Side.SHORT, entry_px, qty)

    def _enter_position(
        self, ts: pd.Timestamp, side: Side, entry_px: float, qty: int
    ) -> None:
        self.position = Position(
            symbol=self.symbol,
            side=side,
            entry_price=entry_px,
            qty=qty,
            entry_time=ts,
        )
        log.info(
            f"ENTRY FILL | {self.symbol} {side.name} x{qty} @ {entry_px:.2f} | "
            f"Time={ts.strftime('%H:%M:%S')} | "
            f"SL={self.position.initial_sl:.2f} | TP={self.position.target:.2f}"
        )

    def _exit_position(
        self, ts: pd.Timestamp, exit_px: float, reason: ExitReason
    ) -> None:
        pos = self.position
        gross_pnl = (exit_px - pos.entry_price) * pos.qty * (
            1 if pos.side == Side.LONG else -1
        )

        trade_record = {
            "date": pos.entry_time.date(),
            "symbol": pos.symbol,
            "side": pos.side.name,
            "entry_time": pos.entry_time,
            "entry_price": round(pos.entry_price, 2),
            "exit_time": ts,
            "exit_price": round(exit_px, 2),
            "qty": pos.qty,
            "gross_pnl": round(gross_pnl, 2),
            "exit_reason": reason.value,
            "initial_sl": round(pos.initial_sl, 2),
            "target": round(pos.target, 2),
            "peak_price": round(pos.peak_price, 2),
        }
        self.trades.append(trade_record)
        _log_trade(pos, ts, exit_px, reason)
        pos.close()
        self.position = None
