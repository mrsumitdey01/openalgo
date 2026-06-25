"""
bot6b/position_manager.py
========================
Handles all position sizing, stop-loss, take-profit, and exits
for Bot6b Hull BBI Strategy.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

try:
    from bot6b.config import MAX_EXPOSURE
except ImportError:
    from config import MAX_EXPOSURE

TARGET_PCT = 0.015
STOP_PCT = 0.0075

class Side(Enum):
    LONG = auto()
    SHORT = auto()
class ExitReason(Enum):
    TARGET_HIT    = "TARGET_HIT"
    STOP_LOSS     = "STOP_LOSS"
    EOD_SQUAREOFF = "EOD_SQUAREOFF"

@dataclass
class Position:
    symbol: str
    side: Side
    entry_price: float
    qty: int
    entry_time: object  # pd.Timestamp

    target: float = field(init=False)
    risk_sl: float = field(init=False)
    peak_price: float = field(init=False)
    is_open: bool = field(default=True, init=False)

    def __post_init__(self):
        self.peak_price = self.entry_price
        if self.side == Side.LONG:
            self.target = self.entry_price * (1 + TARGET_PCT)
            self.risk_sl = self.entry_price * (1 - STOP_PCT)
        else:  # SHORT
            self.target = self.entry_price * (1 - TARGET_PCT)
            self.risk_sl = self.entry_price * (1 + STOP_PCT)

    def update_peak(self, bar_high: float, bar_low: float) -> None:
        if not self.is_open:
            return
        if self.side == Side.LONG:
            if bar_high > self.peak_price:
                self.peak_price = bar_high
        else:
            if bar_low < self.peak_price:
                self.peak_price = bar_low

    def check_exit(
        self,
        bar_high: float,
        bar_low: float,
        bar_close: float,
    ) -> Optional[tuple[float, ExitReason]]:
        if not self.is_open:
            return None

        if self.side == Side.LONG:
            if bar_high >= self.target:
                return (self.target, ExitReason.TARGET_HIT)
            if bar_low <= self.risk_sl:
                return (self.risk_sl, ExitReason.STOP_LOSS)
        else:  # SHORT
            if bar_low <= self.target:
                return (self.target, ExitReason.TARGET_HIT)
            if bar_high >= self.risk_sl:
                return (self.risk_sl, ExitReason.STOP_LOSS)

        return None

    def close(self) -> None:
        self.is_open = False

    def __repr__(self) -> str:
        return (
            f"Position({self.symbol} {self.side.name} x{self.qty} "
            f"@ {self.entry_price:.2f} | SL={self.risk_sl:.2f} "
            f"| TP={self.target:.2f})"
        )

def compute_quantity(entry_price: float) -> int:
    if entry_price <= 0:
        raise ValueError(f"Invalid entry price: {entry_price}")
    qty = math.floor(250000 / entry_price) # Exposure with 5x leverage
    return max(qty, 1)

