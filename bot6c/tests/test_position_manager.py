"""
bot6c/tests/test_position_manager.py
=====================================
Unit tests for position_manager.py — "Trigger and Trail" logic.

Test groups:
    TestPositionSizing       — qty formula, edge cases
    TestInitialRiskLevels    — SL, target, activation price computed correctly
    TestTrailActivation      — trail does NOT activate before threshold
                             — trail DOES activate at exactly +0.3% profit
                             — SL jumps to breakeven on activation
    TestTrailingStopLong     — trail mechanics for LONG positions
    TestTrailingStopShort    — trail mechanics for SHORT positions
    TestExitConditions       — target hit, initial SL, trailing SL priority
    TestNoBackwardMovement   — SL never moves against position
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd
import math

from position_manager import Position, Side, ExitReason, compute_quantity
from config import (
    TARGET_PCT,
    INITIAL_SL_PCT,
    TRAIL_ACTIVATION_PCT,
    TRAIL_PCT,
    MAX_EXPOSURE,
)

ENTRY = 1000.0
TS    = pd.Timestamp("2025-01-02 09:30:00")


def make_pos(side=Side.LONG, price=ENTRY):
    return Position(symbol="TEST", side=side, entry_price=price, qty=250, entry_time=TS)


# =========================================================================== #
# POSITION SIZING
# =========================================================================== #
class TestPositionSizing:
    def test_qty_formula(self):
        assert compute_quantity(1000.0) == math.floor(MAX_EXPOSURE / 1000.0)

    def test_qty_high_price(self):
        assert compute_quantity(5000.0) == math.floor(MAX_EXPOSURE / 5000.0)

    def test_qty_low_price(self):
        assert compute_quantity(100.0) == math.floor(MAX_EXPOSURE / 100.0)

    def test_qty_minimum_one(self):
        assert compute_quantity(500_000.0) == 1

    def test_invalid_price_zero_raises(self):
        with pytest.raises(ValueError):
            compute_quantity(0)

    def test_invalid_price_negative_raises(self):
        with pytest.raises(ValueError):
            compute_quantity(-100)


# =========================================================================== #
# INITIAL RISK LEVELS
# =========================================================================== #
class TestInitialRiskLevels:
    def test_long_initial_sl(self):
        pos = make_pos(Side.LONG, ENTRY)
        assert abs(pos.initial_sl - ENTRY * (1 - INITIAL_SL_PCT)) < 0.001  # 997.0

    def test_long_target(self):
        pos = make_pos(Side.LONG, ENTRY)
        assert abs(pos.target - ENTRY * (1 + TARGET_PCT)) < 0.001  # 1010.0

    def test_long_activation_price(self):
        pos = make_pos(Side.LONG, ENTRY)
        assert abs(pos.trail_activation_price - ENTRY * (1 + TRAIL_ACTIVATION_PCT)) < 0.001  # 1003.0

    def test_short_initial_sl(self):
        pos = make_pos(Side.SHORT, ENTRY)
        assert abs(pos.initial_sl - ENTRY * (1 + INITIAL_SL_PCT)) < 0.001  # 1003.0

    def test_short_target(self):
        pos = make_pos(Side.SHORT, ENTRY)
        assert abs(pos.target - ENTRY * (1 - TARGET_PCT)) < 0.001  # 990.0

    def test_short_activation_price(self):
        pos = make_pos(Side.SHORT, ENTRY)
        assert abs(pos.trail_activation_price - ENTRY * (1 - TRAIL_ACTIVATION_PCT)) < 0.001  # 997.0

    def test_trail_not_active_at_entry(self):
        """Trail must NOT be active immediately — it requires a trigger."""
        pos = make_pos(Side.LONG, ENTRY)
        assert pos.trail_active == False

    def test_trail_sl_equals_initial_sl_before_activation(self):
        """Before trail activates, trail_sl is the hard initial SL."""
        pos = make_pos(Side.LONG, ENTRY)
        assert pos.trail_sl == pos.initial_sl

    def test_trail_sl_equals_initial_sl_short(self):
        pos = make_pos(Side.SHORT, ENTRY)
        assert pos.trail_sl == pos.initial_sl


# =========================================================================== #
# TRAIL ACTIVATION — the most critical section
# =========================================================================== #
class TestTrailActivation:
    def test_trail_does_not_activate_below_threshold_long(self):
        """
        LONG @ 1000: trail activates at 1003.
        A bar that only reaches 1002.99 must NOT activate the trail.
        """
        pos = make_pos(Side.LONG, ENTRY)
        pos.update_trail(bar_high=1002.99, bar_low=999.0)
        assert pos.trail_active == False
        assert pos.trail_sl == pos.initial_sl  # still hard SL

    def test_trail_activates_at_exactly_threshold_long(self):
        """
        LONG @ 1000: trail_activation_price = 1003.0.
        A bar high of exactly 1003.0 must activate the trail.
        """
        pos = make_pos(Side.LONG, ENTRY)
        pos.update_trail(bar_high=1003.0, bar_low=999.0)
        assert pos.trail_active == True

    def test_sl_jumps_to_breakeven_on_activation_long(self):
        """
        On activation, SL must jump from initial_sl (997) to entry (1000).
        """
        pos = make_pos(Side.LONG, ENTRY)
        pos.update_trail(bar_high=1003.0, bar_low=999.0)
        assert pos.trail_active == True
        assert abs(pos.trail_sl - ENTRY) < 0.001  # SL = 1000.00 (breakeven)

    def test_trail_does_not_activate_above_threshold_short(self):
        """
        SHORT @ 1000: trail activates at 997.
        A bar low of 997.01 must NOT activate the trail.
        """
        pos = make_pos(Side.SHORT, ENTRY)
        pos.update_trail(bar_high=1001.0, bar_low=997.01)
        assert pos.trail_active == False
        assert pos.trail_sl == pos.initial_sl

    def test_trail_activates_at_exactly_threshold_short(self):
        """
        SHORT @ 1000: trail_activation_price = 997.0.
        A bar low of exactly 997.0 must activate the trail.
        """
        pos = make_pos(Side.SHORT, ENTRY)
        pos.update_trail(bar_high=1001.0, bar_low=997.0)
        assert pos.trail_active == True

    def test_sl_jumps_to_breakeven_on_activation_short(self):
        """
        On activation, SL must be at-or-better-than breakeven for the position.
        For SHORT: 'better than breakeven' means trail_sl <= entry_price.

        With bar_low=997.0 (the activation bar), peak=997.0.
        trail = 997.0 * (1 + 0.003) = 999.991 — which is BELOW entry (1000.0).
        For a SHORT, lower trail_sl = more protective (exits if price rises to 999.991,
        locking in a small profit rather than merely breaking even).
        The engine correctly selects min(entry, trail_from_peak) = 999.991.
        """
        pos = make_pos(Side.SHORT, ENTRY)
        pos.update_trail(bar_high=1001.0, bar_low=997.0)
        assert pos.trail_active == True
        # SL must be at or below entry (breakeven) — in profit territory for SHORT
        assert pos.trail_sl <= ENTRY + 1e-9, (
            f"Expected trail_sl <= {ENTRY} (breakeven), got {pos.trail_sl}")

    def test_hard_sl_still_active_before_trail_trigger_long(self):
        """
        Before trail activates: a bar hitting initial_sl should still exit via INITIAL_SL.
        """
        pos = make_pos(Side.LONG, ENTRY)
        # No update_trail called → trail not active → trail_sl == initial_sl == 997
        result = pos.check_exit(bar_high=1001.0, bar_low=996.5, bar_close=997.0)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.INITIAL_SL

    def test_hard_sl_still_active_before_trail_trigger_short(self):
        pos = make_pos(Side.SHORT, ENTRY)
        result = pos.check_exit(bar_high=1003.5, bar_low=999.0, bar_close=1002.0)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.INITIAL_SL


# =========================================================================== #
# TRAILING STOP — LONG
# =========================================================================== #
class TestTrailingStopLong:
    def _activated_pos(self, price=ENTRY):
        """Return a LONG position with trail already activated at activation price."""
        pos = make_pos(Side.LONG, price)
        pos.update_trail(bar_high=price * (1 + TRAIL_ACTIVATION_PCT), bar_low=price * 0.999)
        assert pos.trail_active  # sanity
        return pos

    def test_trail_advances_with_new_high(self):
        pos = self._activated_pos()
        pos.update_trail(bar_high=1006.0, bar_low=1001.0)
        # peak = 1006, trail_sl = 1006 * (1 - 0.003) = 1002.982
        expected = 1006.0 * (1 - TRAIL_PCT)
        assert abs(pos.trail_sl - expected) < 0.001

    def test_trail_never_moves_down_long(self):
        pos = self._activated_pos()
        pos.update_trail(bar_high=1008.0, bar_low=1001.0)
        trail_after_high = pos.trail_sl
        # Now price retreats
        pos.update_trail(bar_high=1004.0, bar_low=1001.0)
        assert pos.trail_sl == trail_after_high, "Trail SL moved backward for LONG!"

    def test_peak_updates_correctly_long(self):
        pos = self._activated_pos()
        pos.update_trail(bar_high=1010.0, bar_low=1003.0)
        assert pos.peak_price == 1010.0
        pos.update_trail(bar_high=1005.0, bar_low=1003.0)  # lower high
        assert pos.peak_price == 1010.0  # peak unchanged

    def test_trail_sl_above_breakeven_after_more_profit(self):
        """
        Once trail is active and price moves further, trail_sl must be > entry (above breakeven).
        """
        pos = self._activated_pos()
        pos.update_trail(bar_high=1008.0, bar_low=1003.0)
        assert pos.trail_sl > ENTRY  # SL is now in profitable territory


# =========================================================================== #
# TRAILING STOP — SHORT
# =========================================================================== #
class TestTrailingStopShort:
    def _activated_pos(self, price=ENTRY):
        pos = make_pos(Side.SHORT, price)
        pos.update_trail(bar_high=price * 1.001, bar_low=price * (1 - TRAIL_ACTIVATION_PCT))
        assert pos.trail_active
        return pos

    def test_trail_advances_with_new_low(self):
        pos = self._activated_pos()
        pos.update_trail(bar_high=998.0, bar_low=994.0)
        # peak = 994, trail_sl = 994 * (1 + 0.003) = 996.982
        expected = 994.0 * (1 + TRAIL_PCT)
        assert abs(pos.trail_sl - expected) < 0.001

    def test_trail_never_moves_up_short(self):
        pos = self._activated_pos()
        pos.update_trail(bar_high=998.0, bar_low=992.0)
        trail_after_low = pos.trail_sl
        # Price bounces up (bar_low is higher)
        pos.update_trail(bar_high=999.0, bar_low=996.0)
        assert pos.trail_sl == trail_after_low, "Trail SL moved backward for SHORT!"

    def test_trail_sl_below_breakeven_after_more_profit(self):
        pos = self._activated_pos()
        pos.update_trail(bar_high=998.0, bar_low=992.0)
        assert pos.trail_sl < ENTRY  # SL is now in profitable territory


# =========================================================================== #
# EXIT CONDITIONS
# =========================================================================== #
class TestExitConditions:
    # --- Target ---
    def test_long_target_hit(self):
        pos = make_pos(Side.LONG, ENTRY)
        # Target = 1010.0
        result = pos.check_exit(bar_high=1011.0, bar_low=1005.0, bar_close=1010.0)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.TARGET_HIT
        assert abs(exit_px - pos.target) < 0.001

    def test_short_target_hit(self):
        pos = make_pos(Side.SHORT, ENTRY)
        # Target = 990.0
        result = pos.check_exit(bar_high=992.0, bar_low=989.0, bar_close=990.0)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.TARGET_HIT
        assert abs(exit_px - pos.target) < 0.001

    # --- Initial SL (before trail activates) ---
    def test_long_initial_sl_hit_before_trail(self):
        pos = make_pos(Side.LONG, ENTRY)
        # initial_sl = 997.0, trail NOT active
        result = pos.check_exit(bar_high=1001.0, bar_low=996.0, bar_close=997.0)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.INITIAL_SL

    def test_short_initial_sl_hit_before_trail(self):
        pos = make_pos(Side.SHORT, ENTRY)
        # initial_sl = 1003.0, trail NOT active
        result = pos.check_exit(bar_high=1004.0, bar_low=999.0, bar_close=1003.0)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.INITIAL_SL

    # --- Trailing SL (after trail activates) ---
    def test_long_trailing_sl_after_activation(self):
        """After trail activates (SL at breakeven), price drops to hit the trail."""
        pos = make_pos(Side.LONG, ENTRY)
        # Activate trail: price hits 1003+
        pos.update_trail(bar_high=1005.0, bar_low=1001.0)
        assert pos.trail_active
        # trail_sl = 1005 * (1 - 0.003) = 1001.985
        # Now price drops below trail_sl (bar_low = 1001.0 < 1001.985)
        result = pos.check_exit(bar_high=1004.0, bar_low=1001.0, bar_close=1001.5)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.TRAILING_SL

    def test_short_trailing_sl_after_activation(self):
        """After trail activates (SL at breakeven), price rises to hit the trail."""
        pos = make_pos(Side.SHORT, ENTRY)
        # Activate trail: price drops to 997
        pos.update_trail(bar_high=999.0, bar_low=995.0)
        assert pos.trail_active
        # trail_sl = 995 * (1 + 0.003) = 997.985
        # Now price rises above trail_sl
        result = pos.check_exit(bar_high=998.5, bar_low=996.0, bar_close=998.0)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.TRAILING_SL

    # --- No exit within safe zone ---
    def test_long_no_exit_within_bounds(self):
        pos = make_pos(Side.LONG, ENTRY)
        result = pos.check_exit(bar_high=1002.0, bar_low=999.0, bar_close=1001.0)
        assert result is None

    def test_short_no_exit_within_bounds(self):
        pos = make_pos(Side.SHORT, ENTRY)
        result = pos.check_exit(bar_high=1001.0, bar_low=999.0, bar_close=1000.0)
        assert result is None

    # --- Priority: Target beats SL in same bar ---
    def test_priority_target_over_initial_sl_long(self):
        """If both target (up) and SL (down) are breached in same bar, target wins."""
        pos = make_pos(Side.LONG, ENTRY)
        result = pos.check_exit(
            bar_high=pos.target + 1.0,
            bar_low=pos.initial_sl - 1.0,
            bar_close=pos.initial_sl - 1.0,
        )
        _, reason = result
        assert reason == ExitReason.TARGET_HIT

    def test_priority_target_over_trail_sl_short(self):
        """After trail is active: if both target (down) and trail SL (up) triggered, target wins."""
        pos = make_pos(Side.SHORT, ENTRY)
        # Activate trail
        pos.update_trail(bar_high=999.0, bar_low=994.0)
        assert pos.trail_active
        # Construct a bar where price both hits target AND bounces into trail SL
        result = pos.check_exit(
            bar_high=pos.trail_sl + 0.5,   # trail SL breached
            bar_low=pos.target - 0.5,       # target also breached (price went down to target)
            bar_close=pos.target - 0.5,
        )
        _, reason = result
        assert reason == ExitReason.TARGET_HIT

    # --- Breakeven protection ---
    def test_long_cannot_lose_after_trail_activation(self):
        """
        After trail activates (SL at breakeven), any exit via trailing SL
        should be at or above the entry price — no loss possible.
        """
        pos = make_pos(Side.LONG, ENTRY)
        pos.update_trail(bar_high=1003.0, bar_low=1000.0)
        assert pos.trail_active
        # trail_sl is now at 1000 (breakeven) or above
        assert pos.trail_sl >= ENTRY

    def test_short_cannot_lose_after_trail_activation(self):
        pos = make_pos(Side.SHORT, ENTRY)
        pos.update_trail(bar_high=1000.0, bar_low=997.0)
        assert pos.trail_active
        # trail_sl is now at 1000 (breakeven) or below
        assert pos.trail_sl <= ENTRY


# =========================================================================== #
# FULL SCENARIO TEST — bar by bar simulation
# =========================================================================== #
class TestFullScenario:
    def test_long_full_trigger_trail_then_target(self):
        """
        Simulate a perfect long trade:
        Bar 1: Entry @ 1000 — hard SL at 997, trail not active
        Bar 2: High=1001.5 — below trigger (1003), still hard SL
        Bar 3: High=1003.5 — trail ACTIVATES, SL bumps to 1000
        Bar 4: High=1006   — trail_sl advances to 1006*(1-0.003) = 1002.98
        Bar 5: High=1010   — TARGET HIT at 1010
        """
        pos = make_pos(Side.LONG, ENTRY)

        # Bar 1 — no change
        pos.update_trail(bar_high=1001.0, bar_low=998.0)
        assert not pos.trail_active
        assert pos.trail_sl == pos.initial_sl  # still 997

        # Bar 2 — still below trigger
        pos.update_trail(bar_high=1002.5, bar_low=999.0)
        assert not pos.trail_active

        # Bar 3 — trail activates
        pos.update_trail(bar_high=1003.5, bar_low=1001.0)
        assert pos.trail_active
        # bar_high=1003.5 is 0.35% above activation threshold (1003.0).
        # trail = 1003.5 * (1 - 0.003) = 1000.4895 — already above breakeven.
        # The engine correctly advances to 1000.4895 rather than capping at breakeven.
        # Invariant: trail_sl MUST be >= entry (breakeven) for LONG once trail is active.
        assert pos.trail_sl >= ENTRY, (
            f"Expected trail_sl >= {ENTRY} (breakeven), got {pos.trail_sl}")

        # Bar 4 — trail advances
        pos.update_trail(bar_high=1006.0, bar_low=1001.5)
        expected_trail = 1006.0 * (1 - TRAIL_PCT)
        assert abs(pos.trail_sl - expected_trail) < 0.001

        # Bar 5 — target hit
        result = pos.check_exit(bar_high=1011.0, bar_low=1003.0, bar_close=1010.0)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.TARGET_HIT
        assert abs(exit_px - pos.target) < 0.001

    def test_short_full_trigger_trail_then_trailing_exit(self):
        """
        Simulate a short trade where trail activates then price bounces:
        Bar 1: High=1001, Low=999 — no trail
        Bar 2: High=999,  Low=997 — trail ACTIVATES, SL → 1000
        Bar 3: High=997,  Low=993 — trail_sl → 993 * 1.003 = 995.979
        Bar 4: High=997,  Low=995 — price bounces into trail SL → TRAILING_SL exit
        """
        pos = make_pos(Side.SHORT, ENTRY)

        pos.update_trail(bar_high=1001.0, bar_low=999.0)
        assert not pos.trail_active

        pos.update_trail(bar_high=999.0, bar_low=997.0)
        assert pos.trail_active
        assert abs(pos.trail_sl - ENTRY) < 0.01  # SL at breakeven

        pos.update_trail(bar_high=997.0, bar_low=993.0)
        expected_trail = 993.0 * (1 + TRAIL_PCT)
        assert abs(pos.trail_sl - expected_trail) < 0.001

        # Bar 4: price bounces, bar_high breaches trail_sl
        result = pos.check_exit(bar_high=996.5, bar_low=994.0, bar_close=995.5)
        assert result is not None
        exit_px, reason = result
        assert reason == ExitReason.TRAILING_SL
        # Exit should be at or below breakeven (profitable exit for short)
        assert exit_px <= ENTRY
