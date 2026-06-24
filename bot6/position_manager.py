"""
bot6/position_manager.py
========================
Handles all position sizing, stop-loss, take-profit, and trailing stop logic
for Bot6 DTC Intraday Strategy.

RISK MANAGEMENT: "TRIGGER AND TRAIL" LOGIC
-------------------------------------------
Phase 1 — INITIAL (trail not yet active):
    Only the hard SL at 0.3% from entry protects the position.
    Trail does NOT activate until the position reaches +0.3% profit.

Phase 2 — TRAIL ACTIVE (triggered at +0.3% profit):
    Activation event: SL immediately jumps to BREAKEVEN (entry price).
    From that point forward: SL trails 0.3% behind the running peak.
    SL NEVER moves backward (against the position).

Hard Max Profit: Position closes immediately at +1.0% from entry.
    This is a ceiling — no trailing beyond this level.

Example — LONG at Rs.1000:
    Hard SL          = 997.00   ← active from bar 1
    Trail activates  → when price reaches 1003.00 (+0.3%)
    SL on activation = 1000.00  ← breakeven
    Trail thereafter = peak * (1 - 0.003), e.g., peak=1006 → SL=1002.98
    Hard Target      = 1010.00  ← exits immediately if hit

Example — SHORT at Rs.1000:
    Hard SL          = 1003.00  ← active from bar 1
    Trail activates  → when price drops to 997.00 (-0.3%)
    SL on activation = 1000.00  ← breakeven
    Trail thereafter = peak * (1 + 0.003), e.g., peak=994 → SL=996.98
    Hard Target      =  990.00  ← exits immediately if hit
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from config import (
    MAX_EXPOSURE,
    TARGET_PCT,
    INITIAL_SL_PCT,
    TRAIL_ACTIVATION_PCT,
    TRAIL_PCT,
)


class Side(Enum):
    LONG = auto()
    SHORT = auto()


class ExitReason(Enum):
    TARGET_HIT    = "TARGET_HIT"
    TRAILING_SL   = "TRAILING_SL"
    INITIAL_SL    = "INITIAL_SL"
    EOD_SQUAREOFF = "EOD_SQUAREOFF"
    SIGNAL_REVERSAL = "SIGNAL_REVERSAL"


@dataclass
class Position:
    """
    Represents a single open intraday position with Trigger-and-Trail logic.

    State machine
    -------------
    trail_active = False  →  only hard SL protects the position
    trail_active = True   →  trail has been triggered; SL is at breakeven or better
    """

    symbol: str
    side: Side
    entry_price: float
    qty: int
    entry_time: object  # pd.Timestamp

    # Fixed risk levels — computed at entry, never change
    initial_sl: float = field(init=False)   # Hard stop: entry ± 0.3%
    target: float = field(init=False)        # Hard max profit: entry ± 1.0%
    trail_activation_price: float = field(init=False)  # Price that triggers the trail

    # Dynamic state — updated each bar
    trail_active: bool = field(default=False, init=False)
    trail_sl: float = field(init=False)     # Current stop level (hard SL until activated)
    peak_price: float = field(init=False)   # Best favorable price seen since entry

    is_open: bool = field(default=True, init=False)

    def __post_init__(self):
        if self.side == Side.LONG:
            self.initial_sl            = self.entry_price * (1 - INITIAL_SL_PCT)
            self.target                = self.entry_price * (1 + TARGET_PCT)
            self.trail_activation_price = self.entry_price * (1 + TRAIL_ACTIVATION_PCT)
            self.trail_sl              = self.initial_sl   # starts as hard SL
            self.peak_price            = self.entry_price
        else:  # SHORT
            self.initial_sl            = self.entry_price * (1 + INITIAL_SL_PCT)
            self.target                = self.entry_price * (1 - TARGET_PCT)
            self.trail_activation_price = self.entry_price * (1 - TRAIL_ACTIVATION_PCT)
            self.trail_sl              = self.initial_sl
            self.peak_price            = self.entry_price

    # ---------------------------------------------------------------------- #
    # CORE UPDATE — called once per bar BEFORE checking exits
    # ---------------------------------------------------------------------- #
    def update_trail(self, bar_high: float, bar_low: float) -> None:
        """
        Update trailing stop state for the current bar.

        Step 1 — Check if trail should be activated:
            LONG:  bar_high >= trail_activation_price (+0.3% from entry)
            SHORT: bar_low  <= trail_activation_price (-0.3% from entry)

        Step 2 — If trail is now active, update peak and recalculate trail SL:
            LONG:  trail_sl = max(trail_sl, peak * (1 - TRAIL_PCT))
            SHORT: trail_sl = min(trail_sl, peak * (1 + TRAIL_PCT))
            The trail SL NEVER moves against the position.

        Note: Activation bump to breakeven happens atomically the first time
        trail_active flips True. Peak is seeded from the activation bar.
        """
        if not self.is_open:
            return

        if self.side == Side.LONG:
            # --- Step 1: Activation check ---
            if not self.trail_active and bar_high >= self.trail_activation_price:
                self.trail_active = True
                # Bump SL to breakeven immediately on activation
                self.trail_sl = self.entry_price
                # Seed peak from the activation bar's high
                self.peak_price = bar_high

            # --- Step 2: Advance trail (only when active) ---
            if self.trail_active:
                if bar_high > self.peak_price:
                    self.peak_price = bar_high
                new_trail = self.peak_price * (1 - TRAIL_PCT)
                # Trail SL can only move UP (tighter), never down
                if new_trail > self.trail_sl:
                    self.trail_sl = new_trail

        else:  # SHORT
            # --- Step 1: Activation check ---
            if not self.trail_active and bar_low <= self.trail_activation_price:
                self.trail_active = True
                # Bump SL to breakeven immediately on activation
                self.trail_sl = self.entry_price
                # Seed peak from the activation bar's low
                self.peak_price = bar_low

            # --- Step 2: Advance trail (only when active) ---
            if self.trail_active:
                if bar_low < self.peak_price:
                    self.peak_price = bar_low
                new_trail = self.peak_price * (1 + TRAIL_PCT)
                # Trail SL can only move DOWN (tighter), never up
                if new_trail < self.trail_sl:
                    self.trail_sl = new_trail

    # ---------------------------------------------------------------------- #
    # EXIT CHECK — called each bar AFTER update_trail
    # ---------------------------------------------------------------------- #
    def check_exit(
        self,
        bar_high: float,
        bar_low: float,
        bar_close: float,
    ) -> Optional[tuple[float, ExitReason]]:
        """
        Check if this bar triggers an exit condition.

        Exit priority order (highest to lowest):
            1. Hard Target Hit (+1.0%)   — always exits first if both conditions met
            2. Trail SL / Hard SL breach — whichever is the active stop

        For the current bar:
            - trail_sl reflects the UPDATED trail (after update_trail() is called)
            - If trail is not yet active, trail_sl == initial_sl (the hard stop)

        Returns
        -------
        (exit_price, ExitReason) if exit triggered, None otherwise.
        """
        if not self.is_open:
            return None

        if self.side == Side.LONG:
            # 1. Hard Target — price hit +1.0% ceiling
            if bar_high >= self.target:
                return (self.target, ExitReason.TARGET_HIT)

            # 2. Stop loss (trail_sl is initial_sl when trail not yet active;
            #              breakeven or better once trail is active)
            if bar_low <= self.trail_sl:
                reason = ExitReason.TRAILING_SL if self.trail_active else ExitReason.INITIAL_SL
                return (self.trail_sl, reason)

        else:  # SHORT
            # 1. Hard Target — price hit -1.0% ceiling (price dropped to target)
            if bar_low <= self.target:
                return (self.target, ExitReason.TARGET_HIT)

            # 2. Stop loss
            if bar_high >= self.trail_sl:
                reason = ExitReason.TRAILING_SL if self.trail_active else ExitReason.INITIAL_SL
                return (self.trail_sl, reason)

        return None

    def close(self) -> None:
        self.is_open = False

    def __repr__(self) -> str:
        state = "TRAIL_ACTIVE" if self.trail_active else "INITIAL_SL"
        return (
            f"Position({self.symbol} {self.side.name} x{self.qty} "
            f"@ {self.entry_price:.2f} | [{state}] SL={self.trail_sl:.2f} "
            f"| TP={self.target:.2f} | Peak={self.peak_price:.2f})"
        )


def compute_quantity(entry_price: float) -> int:
    """
    Dynamic position sizing:
        Max_Exposure = CAPITAL_PER_TRADE * LEVERAGE = Rs 2,50,000
        Qty = floor(Max_Exposure / Entry_Price)

    Ensures at least 1 share is always returned.
    """
    if entry_price <= 0:
        raise ValueError(f"Invalid entry price: {entry_price}")
    qty = math.floor(MAX_EXPOSURE / entry_price)
    return max(qty, 1)
