"""
===============================================================================
  OPTIONS_EXECUTION.PY -- Spread Builder + Risk Management
  ---------------------------------------------------------
  Handles the full lifecycle of options spreads:

    1. ATM strike selection (round spot to nearest 100)
    2. Bull Call Spread (BUY ATM CE + SELL ATM+500 CE)
    3. Bear Put Spread  (BUY ATM PE + SELL ATM-500 PE)
    4. Leg protection    (if one leg fails, unwind the other)
    5. Exit on opposite signal
    6. 15% spread P&L stop
    7. 5-candle spot structural stop
    8. Position state recovery after crash/reconnect
===============================================================================
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from hullbot import config
from hullbot.broker.base import BaseBroker, Side, Signal, OrderResponse, OrderStatus
from hullbot.db import state_db

logger = logging.getLogger(__name__)


# =============================================================================
#  SPREAD STATE DATACLASS
# =============================================================================

@dataclass
class SpreadState:
    """Tracks the current active spread and its risk parameters.

    Created when a spread is successfully entered.
    Destroyed when the spread is closed (exit signal, stop, or EOD).
    """
    spread_type: Signal         # LONG or SHORT
    entry_time: float           # Unix timestamp of entry
    entry_cost: float           # Net premium paid per unit (ATM_ltp - OTM_ltp)
    atm_symbol: str             # ATM leg broker symbol
    otm_symbol: str             # OTM leg broker symbol
    atm_order_id: str           # ATM leg order ID
    otm_order_id: str           # OTM leg order ID
    qty: int                    # Quantity per leg
    structural_stop: float      # Spot level for structural exit
    db_row_id: int = -1         # SQLite database row ID tracking this spread


# =============================================================================
#  OPTIONS EXECUTION MANAGER
# =============================================================================

class OptionsExecutionManager:
    """Manages the complete options spread lifecycle.

    Only ONE spread can be active at a time.
    The bot never holds naked options -- every position is a defined-risk
    spread with known max loss.
    """

    def __init__(self, broker: BaseBroker) -> None:
        self._broker = broker
        self._active_spread: Optional[SpreadState] = None
        self._is_executing = False

    @property
    def is_executing(self) -> bool:
        """True if the bot is actively building or closing a spread (blocks reconciliation)."""
        return self._is_executing

    @property
    def _qty_per_leg(self) -> int:
        """Dynamically fetch the latest quantity based on real-time config settings."""
        return config.LOT_SIZE * config.LOT_MULTIPLIER

    @property
    def has_active_spread(self) -> bool:
        """True if there's an active spread being monitored."""
        return self._active_spread is not None

    @property
    def active_spread(self) -> Optional[SpreadState]:
        """The current active SpreadState (or None)."""
        return self._active_spread

    # =========================================================================
    #  STRIKE SELECTION
    # =========================================================================

    @staticmethod
    def get_atm_strike(spot_price: float) -> int:
        """Round spot price to nearest strike interval (100).

        Examples:
            52,347  ->  52,300  (rounds down)
            52,378  ->  52,400  (rounds up)
            52,350  ->  52,400  (Python rounds 0.5 up)
        """
        return round(spot_price / config.STRIKE_INTERVAL) * config.STRIKE_INTERVAL

    # =========================================================================
    #  SPREAD ENTRY -- BULL CALL
    # =========================================================================

    async def execute_bull_call_spread(
        self,
        spot_price: float,
        bnf_df: pd.DataFrame,
    ) -> bool:
        """Build and execute a Bull Call Spread on a LONG signal.

        Structure:
            BUY  1 lot ATM CE     (profit leg)
            SELL 1 lot ATM+400 CE (hedge leg, caps upside)

        Both legs fire simultaneously via asyncio.gather().
        If one fills and the other doesn't, the Leg Protection Protocol
        kicks in to prevent naked exposure.

        Args:
            spot_price: Current Bank Nifty spot price (for ATM calc)
            bnf_df:     Bank Nifty OHLCV DataFrame (for structural stop)

        Returns:
            True if the spread was successfully placed and both legs filled.
        """
        if self._active_spread is not None:
            logger.warning("Cannot enter Bull Call -- spread already active")
            return False

        atm = self.get_atm_strike(spot_price)
        is_nifty = (config.OPTION_UNDERLYING == "NIFTY")
        spread_width = 200 if is_nifty else 500
        otm = atm + spread_width

        expiry = await self._broker.get_current_expiry(config.OPTION_UNDERLYING)

        # -- Build option symbols via broker --
        atm_sym = await self._broker.build_option_symbol(
            config.OPTION_UNDERLYING, expiry, atm, "CE"
        )
        otm_sym = await self._broker.build_option_symbol(
            config.OPTION_UNDERLYING, expiry, otm, "CE"
        )

        logger.info(
            "BULL CALL SPREAD: BUY %s / SELL %s (ATM=%d OTM=%d)",
            atm_sym, otm_sym, atm, otm,
        )

        # -- Get current LTPs for pricing --
        atm_ltp = await self._broker.get_ltp(atm_sym)
        otm_ltp = await self._broker.get_ltp(otm_sym)

        if atm_ltp <= 0:
            logger.error("ATM LTP is 0 or negative -- cannot price spread")
            return False

        self._is_executing = True
        try:
            # -- Step 0: Write PENDING_SPREAD to DB --
            db_row_id = await state_db.log_pending_spread(
                "BULL_CALL", atm_sym, otm_sym, self._qty_per_leg
            )

            # -- Step 1: Place the BUY (ATM) Leg with Limit Chasing --
            buy_resp = await self._place_and_chase_order(atm_sym, Side.BUY, self._qty_per_leg)
            if not buy_resp:
                logger.error("BUY leg chasing failed or max slippage breached. Trade aborted.")
                asyncio.create_task(state_db.mark_closed(db_row_id))
                return False
            
            asyncio.create_task(state_db.update_leg_order(db_row_id, "atm", buy_resp.order_id))
    
            # -- Step 2: Place the SELL (OTM) Leg with Limit Chasing --
            sell_resp = await self._place_and_chase_order(otm_sym, Side.SELL, self._qty_per_leg)
            if not sell_resp:
                # EMERGENCY UNWIND: Place market order to close the BUY leg to prevent naked exposure
                logger.critical("SELL leg chasing failed. EMERGENCY: unwinding filled BUY leg %s", atm_sym)
                try:
                    await self._broker.place_market_order(
                        atm_sym, Side.SELL, self._qty_per_leg
                    )
                except Exception as exc:
                    logger.error("CRITICAL: Failed to unwind filled BUY leg: %s -- manual intervention required!", exc)
                asyncio.create_task(state_db.mark_closed(db_row_id))
                return False
    
            sell_order_id = sell_resp.order_id
            asyncio.create_task(state_db.update_leg_order(db_row_id, "otm", sell_order_id))
    
            # -- Calculate entry cost and structural stop --
            # Use actual filled average prices if available
            buy_cost = buy_resp.avg_price if buy_resp.avg_price > 0 else atm_ltp
            sell_credit = sell_resp.avg_price if sell_resp.avg_price > 0 else otm_ltp
            entry_cost = buy_cost - sell_credit
            structural_stop = self._compute_structural_stop(bnf_df, Signal.LONG)
    
            # -- Record spread state --
            self._active_spread = SpreadState(
                spread_type=Signal.LONG,
                entry_time=time.time(),
                entry_cost=entry_cost,
                atm_symbol=atm_sym,
                otm_symbol=otm_sym,
                atm_order_id=buy_resp.order_id,
                otm_order_id=sell_order_id,
                qty=self._qty_per_leg,
                structural_stop=structural_stop,
                db_row_id=db_row_id
            )
            asyncio.create_task(state_db.mark_active(db_row_id, entry_cost, structural_stop, self._active_spread.entry_time))
    
            logger.info(
                "BULL CALL SPREAD ACTIVE | Cost=%.2f/unit | "
                "Stop=%.2f | Qty=%d",
                entry_cost, structural_stop, self._qty_per_leg,
            )
            return True
        finally:
            self._is_executing = False
        
    # =========================================================================
    #  SPREAD ENTRY -- BEAR PUT
    # =========================================================================

    async def execute_bear_put_spread(
        self,
        spot_price: float,
        bnf_df: pd.DataFrame,
    ) -> bool:
        """Build and execute a Bear Put Spread on a SHORT signal.

        Structure:
            BUY  1 lot ATM PE     (profit leg)
            SELL 1 lot ATM-400 PE (hedge leg, caps downside profit)

        Args:
            spot_price: Current Bank Nifty spot price
            bnf_df:     Bank Nifty OHLCV DataFrame (for structural stop)

        Returns:
            True if spread successfully placed.
        """
        if self._active_spread is not None:
            logger.warning("Cannot enter Bear Put -- spread already active")
            return False

        atm = self.get_atm_strike(spot_price)
        is_nifty = (config.OPTION_UNDERLYING == "NIFTY")
        spread_width = 200 if is_nifty else 500
        otm = atm - spread_width

        expiry = await self._broker.get_current_expiry(config.OPTION_UNDERLYING)

        atm_sym = await self._broker.build_option_symbol(
            config.OPTION_UNDERLYING, expiry, atm, "PE"
        )
        otm_sym = await self._broker.build_option_symbol(
            config.OPTION_UNDERLYING, expiry, otm, "PE"
        )

        logger.info(
            "BEAR PUT SPREAD: BUY %s / SELL %s (ATM=%d OTM=%d)",
            atm_sym, otm_sym, atm, otm,
        )

        atm_ltp = await self._broker.get_ltp(atm_sym)
        otm_ltp = await self._broker.get_ltp(otm_sym)

        if atm_ltp <= 0:
            logger.error("ATM LTP is 0 or negative -- cannot price spread")
            return False

        self._is_executing = True
        try:
            # -- Step 0: Write PENDING_SPREAD to DB --
            db_row_id = await state_db.log_pending_spread(
                "BEAR_PUT", atm_sym, otm_sym, self._qty_per_leg
            )

            # -- Step 1: Place the BUY (ATM) Leg with Limit Chasing --
            buy_resp = await self._place_and_chase_order(atm_sym, Side.BUY, self._qty_per_leg)
            if not buy_resp:
                logger.error("BUY leg chasing failed or max slippage breached. Trade aborted.")
                asyncio.create_task(state_db.mark_closed(db_row_id))
                return False

            asyncio.create_task(state_db.update_leg_order(db_row_id, "atm", buy_resp.order_id))

            # -- Step 2: Place the SELL (OTM) Leg with Limit Chasing --
            sell_resp = await self._place_and_chase_order(otm_sym, Side.SELL, self._qty_per_leg)
            if not sell_resp:
                # EMERGENCY UNWIND: Place market order to close the BUY leg to prevent naked exposure
                logger.critical("SELL leg chasing failed. EMERGENCY: unwinding filled BUY leg %s", atm_sym)
                try:
                    await self._broker.place_market_order(
                        atm_sym, Side.SELL, self._qty_per_leg
                    )
                except Exception as exc:
                    logger.error("CRITICAL: Failed to unwind filled BUY leg: %s -- manual intervention required!", exc)
                asyncio.create_task(state_db.mark_closed(db_row_id))
                return False

            sell_order_id = sell_resp.order_id
            asyncio.create_task(state_db.update_leg_order(db_row_id, "otm", sell_order_id))

            # -- Calculate entry cost and structural stop --
            buy_cost = buy_resp.avg_price if buy_resp.avg_price > 0 else atm_ltp
            sell_credit = sell_resp.avg_price if sell_resp.avg_price > 0 else otm_ltp
            entry_cost = buy_cost - sell_credit
            structural_stop = self._compute_structural_stop(bnf_df, Signal.SHORT)

            # -- Record spread state --
            self._active_spread = SpreadState(
                spread_type=Signal.SHORT,
                entry_time=time.time(),
                entry_cost=entry_cost,
                atm_symbol=atm_sym,
                otm_symbol=otm_sym,
                atm_order_id=buy_resp.order_id,
                otm_order_id=sell_order_id,
                qty=self._qty_per_leg,
                structural_stop=structural_stop,
                db_row_id=db_row_id
            )
            asyncio.create_task(state_db.mark_active(db_row_id, entry_cost, structural_stop, self._active_spread.entry_time))

            logger.info(
                "BEAR PUT SPREAD ACTIVE | Cost=%.2f/unit | "
                "Stop=%.2f | Qty=%d",
                entry_cost, structural_stop, self._qty_per_leg,
            )
            return True
        finally:
            self._is_executing = False
        
    # =========================================================================
    #  LIMIT CHASING ENGINE
    # =========================================================================

    async def _place_and_chase_order(
        self,
        symbol: str,
        side: Side,
        qty: int,
    ) -> OrderResponse | None:
        """Place limit order at Bid/Ask and chase price if unfilled via PUT modification."""
        try:
            bid, ask, ltp = await self._broker.get_quote(symbol)
        except Exception as exc:
            logger.error("Failed to get quote for %s: %s", symbol, exc)
            return None
        
        # Start at Bid for BUY, Ask for SELL to capture spread edge
        current_price = bid if side == Side.BUY else ask
        
        if current_price <= 0:
            current_price = ltp

        is_nifty = (config.OPTION_UNDERLYING == "NIFTY")
        max_slippage = config.NIFTY_CHASE_MAX_SLIPPAGE_POINTS if is_nifty else config.BNF_CHASE_MAX_SLIPPAGE_POINTS
        step = config.NIFTY_CHASE_STEP_POINTS if is_nifty else config.BNF_CHASE_STEP_POINTS
        interval = config.NIFTY_CHASE_INTERVAL_SECS if is_nifty else config.BNF_CHASE_INTERVAL_SECS
        max_retries = config.NIFTY_CHASE_MAX_RETRIES if is_nifty else config.BNF_CHASE_MAX_RETRIES

        max_price = current_price + max_slippage if side == Side.BUY else current_price - max_slippage
        if side == Side.SELL:
            max_price = max(max_price, 0.05)

        logger.info(
            "CHASING %s %s: Start=%.2f Max=%.2f Step=%.2f Interval=%.1fs",
            side.name, symbol, current_price, max_price, step, interval
        )

        resp = await self._broker.place_limit_order(symbol, side, qty, current_price)
        if not resp or resp.status == OrderStatus.REJECTED:
            logger.error("Initial limit rejected: %s", resp.message if resp else "No resp")
            return None

        order_id = resp.order_id
        
        retries = 0
        # Poll and modify loop
        while True:
            status = await self._broker.get_order_status(order_id)
            if status.status == OrderStatus.FILLED:
                logger.info("Chased order FILLED at %.2f", status.avg_price)
                return status
            if status.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
                logger.error("Chased order failed/cancelled: %s", status.message)
                return None

            if retries >= max_retries:
                logger.error("Max retries hit for %s %s (%d). Aborting.", side.name, symbol, max_retries)
                await self._emergency_cancel(order_id)
                return None

            # Not filled. Shift price
            if side == Side.BUY:
                current_price += step
                current_price = round(current_price, 2)
                if current_price > max_price:
                    logger.error("Max slippage hit for BUY %s (%.2f > %.2f). Aborting.", symbol, current_price, max_price)
                    await self._emergency_cancel(order_id)
                    return None
            else:
                current_price -= step
                current_price = round(current_price, 2)
                if current_price < max_price:
                    logger.error("Max slippage hit for SELL %s (%.2f < %.2f). Aborting.", symbol, current_price, max_price)
                    await self._emergency_cancel(order_id)
                    return None

            await asyncio.sleep(interval)
            retries += 1
            logger.info("Chasing %s %s: Modifying price to %.2f (Retry %d/%d)", side.name, symbol, current_price, retries, max_retries)
            try:
                mod_resp = await self._broker.modify_order(order_id, current_price)
                if mod_resp.status == OrderStatus.REJECTED:
                    logger.error("Modify rejected: %s. Aborting.", mod_resp.message)
                    await self._emergency_cancel(order_id)
                    return None
            except Exception as exc:
                logger.warning("Exception during modify_order (order might be filled concurrently): %s", exc)


    async def _wait_for_fill(
        self,
        order_id: str,
        timeout: float,
    ) -> bool:
        """Poll order status until filled, rejected, or timeout.

        Polls every 500ms.  Returns True if FILLED.
        """
        if not order_id:
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            status = await self._broker.get_order_status(order_id)
            if status.status == OrderStatus.FILLED:
                return True
            if status.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
                return False
            await asyncio.sleep(0.5)    # Poll every 500ms

        return False    # Timed out

    async def _emergency_cancel(self, order_id: str) -> None:
        """Best-effort cancel of a pending order during error handling."""
        try:
            await self._broker.cancel_order(order_id)
        except Exception as exc:
            logger.error(
                "Emergency cancel failed for %s: %s", order_id, exc
            )

    # =========================================================================
    #  SPREAD EXIT
    # =========================================================================

    async def close_spread(self) -> None:
        """Close all legs of the active spread at market.

        Fires market orders for BOTH legs simultaneously to minimize
        slippage between unwinding the two sides.

        For both Bull Call and Bear Put spreads:
            - ATM leg was BOUGHT  -> SELL to close
            - OTM leg was SOLD   -> BUY to close
        """
        if self._active_spread is None:
            logger.warning("No active spread to close")
            return

        self._is_executing = True
        try:
            spread = self._active_spread
            self._active_spread = None

            logger.info(
                "CLOSING %s spread: %s + %s",
                spread.spread_type.value,
                spread.atm_symbol,
                spread.otm_symbol,
            )

            # ATM leg was BOUGHT at entry -> SELL to close
            # OTM leg was SOLD at entry   -> BUY to close
            atm_close = self._broker.place_market_order(
                spread.atm_symbol, Side.SELL, spread.qty
            )
            otm_close = self._broker.place_market_order(
                spread.otm_symbol, Side.BUY, spread.qty
            )

            await asyncio.gather(atm_close, otm_close)
            logger.info("Spread closed")
            if spread.db_row_id != -1:
                asyncio.create_task(state_db.mark_closed(spread.db_row_id))
        except Exception as exc:
            logger.error("Error closing spread: %s -- may need manual cleanup", exc)
        finally:
            self._is_executing = False

    # =========================================================================
    #  RISK-BASED EXITS (checked every candle)
    # =========================================================================

    async def check_exit_conditions(
        self,
        bnf_df: pd.DataFrame,
    ) -> bool:
        """Check risk-based exit conditions on every candle close.

        Two independent checks:
          1. Spread P&L Stop:  -15% of initial spread cost
          2. Spot Structural Stop:  Spot price breaches the structural level

        These are INDEPENDENT of signal conditions.  They fire even if
        the opposite signal conditions are NOT met.

        Returns True if an exit was triggered (spread was closed).
        """
        if self._active_spread is None:
            return False

        # ---- Exit 1: Spread P&L Stop (15%) ----
        pnl_triggered = await self._check_pnl_stop()
        if pnl_triggered:
            return True

        # ---- Exit 2: Spot Structural Stop ----
        structural_triggered = self._check_structural_stop(bnf_df)
        if structural_triggered:
            logger.info(
                "STRUCTURAL STOP triggered -- Spot breached %.2f",
                self._active_spread.structural_stop,
            )
            await self.close_spread()
            return True

        return False

    async def _check_pnl_stop(self) -> bool:
        """Check if the spread has lost more than SPREAD_STOP_LOSS_PCT.

        Calculates current spread value by fetching LTP of both legs.
        If the loss exceeds the threshold, closes the spread immediately.

        Spread value = ATM premium - OTM premium (what you'd receive
        if you closed right now, minus what you'd pay).
        """
        if self._active_spread is None:
            return False

        spread = self._active_spread

        try:
            atm_ltp = await self._broker.get_ltp(spread.atm_symbol)
            otm_ltp = await self._broker.get_ltp(spread.otm_symbol)
        except Exception as exc:
            logger.error("LTP fetch failed during P&L check: %s", exc)
            return False

        if atm_ltp <= 0:
            return False    # Can't compute P&L without price

        # Current spread value (per unit)
        current_value = atm_ltp - otm_ltp

        # Loss = what we paid - what we'd get now
        loss = spread.entry_cost - current_value

        # Threshold
        max_loss = spread.entry_cost * config.SPREAD_STOP_LOSS_PCT

        if loss >= max_loss:
            logger.info(
                "P&L STOP triggered | Entry=%.2f Current=%.2f "
                "Loss=%.2f (%.1f%%)",
                spread.entry_cost, current_value,
                loss, (loss / max(spread.entry_cost, 0.01)) * 100,
            )
            await self.close_spread()
            return True

        return False

    def _check_structural_stop(self, bnf_df: pd.DataFrame) -> bool:
        """Check if Bank Nifty spot has breached the structural stop.

        LONG:  Exit if current candle CLOSE < structural_stop
               (Lowest Low of last N candles at time of entry)
        SHORT: Exit if current candle CLOSE > structural_stop
               (Highest High of last N candles at time of entry)

        IMPORTANT: We use candle CLOSE, not intra-candle LTP.
        Options P&L fluctuations are completely ignored -- only the
        spot structure matters.
        """
        if self._active_spread is None:
            return False

        current_close = float(bnf_df["close"].iloc[-1])
        stop = self._active_spread.structural_stop

        if self._active_spread.spread_type == Signal.LONG:
            return current_close < stop
        else:
            return current_close > stop

    def _compute_structural_stop(
        self,
        bnf_df: pd.DataFrame,
        signal: Signal,
    ) -> float:
        """Calculate the structural stop level at time of entry.

        LONG:  Lowest Low of the last STRUCTURAL_STOP_LOOKBACK candles
        SHORT: Highest High of the last STRUCTURAL_STOP_LOOKBACK candles

        This level is computed ONCE at entry and stored in SpreadState.
        It does NOT update as new candles arrive.
        """
        lookback = config.STRUCTURAL_STOP_LOOKBACK

        if signal == Signal.LONG:
            stop = float(bnf_df["low"].iloc[-lookback:].min())
            logger.info(
                "Structural Stop (LONG): Lowest Low of last %d "
                "candles = %.2f",
                lookback, stop,
            )
            return stop
        else:
            stop = float(bnf_df["high"].iloc[-lookback:].max())
            logger.info(
                "Structural Stop (SHORT): Highest High of last %d "
                "candles = %.2f",
                lookback, stop,
            )
            return stop

    # =========================================================================
    #  STATE RECOVERY (Crash Protection)
    # =========================================================================

    async def recover_state(self) -> None:
        """Called on startup -- check for orphan positions and DB state recovery."""
        try:
            positions = await self._broker.get_positions()
            open_positions = {p.symbol: p for p in positions if p.qty != 0}
        except Exception as exc:
            logger.error("Position recovery check failed: %s", exc)
            return

        open_trades = await state_db.get_open_trades()
        if open_trades:
            for trade in open_trades:
                row_id = trade['id']
                if trade['status'] == 'ACTIVE':
                    atm_sym = trade['atm_symbol']
                    otm_sym = trade['otm_symbol']

                    # Check if the spread was partially closed before the crash
                    if atm_sym not in open_positions or otm_sym not in open_positions:
                        logger.critical("Recovery: ACTIVE trade in DB is missing legs in Broker (mid-close crash). Flattening remaining.")
                        for sym in (atm_sym, otm_sym):
                            if sym in open_positions:
                                pos = open_positions.pop(sym)
                                close_side = Side.SELL if pos.qty > 0 else Side.BUY
                                try:
                                    await self._broker.place_market_order(sym, close_side, abs(pos.qty))
                                except Exception as e:
                                    logger.error("Recovery: Failed to flatten orphaned active leg %s: %s", sym, e)
                        asyncio.create_task(state_db.mark_closed(row_id))
                        continue

                    logger.info("Recovery: Found ACTIVE trade in DB. Rebuilding memory map.")
                    # Reconstruct active spread
                    self._active_spread = SpreadState(
                        spread_type=Signal.LONG if trade['spread_type'] == 'BULL_CALL' else Signal.SHORT,
                        entry_time=trade['entry_time'] or time.time(),
                        entry_cost=trade['entry_cost'] or 0.0,
                        atm_symbol=atm_sym,
                        otm_symbol=otm_sym,
                        atm_order_id=trade['atm_order_id'] or "",
                        otm_order_id=trade['otm_order_id'] or "",
                        qty=trade['qty'] or self._qty_per_leg,
                        structural_stop=trade['structural_stop'] or 0.0,
                        db_row_id=row_id
                    )
                    
                    open_positions.pop(atm_sym, None)
                    open_positions.pop(otm_sym, None)
                
                elif trade['status'] == 'PENDING_SPREAD':
                    logger.critical("Recovery: Found PENDING_SPREAD in DB (crashed mid-execution). Flattening exposure.")
                    # Cancel any orders we have IDs for
                    if trade['atm_order_id']:
                        await self._emergency_cancel(trade['atm_order_id'])
                    if trade['otm_order_id']:
                        await self._emergency_cancel(trade['otm_order_id'])
                    
                    # Flatten any open leg
                    for sym in (trade['atm_symbol'], trade['otm_symbol']):
                        if sym in open_positions:
                            pos = open_positions[sym]
                            close_side = Side.SELL if pos.qty > 0 else Side.BUY
                            try:
                                await self._broker.place_market_order(sym, close_side, abs(pos.qty))
                                logger.info("Recovery: Flattened partial leg %s", sym)
                            except Exception as e:
                                logger.error("Recovery: Failed to flatten leg %s: %s", sym, e)
                            open_positions.pop(sym, None)
                    
                    asyncio.create_task(state_db.mark_closed(row_id))

        if not open_positions:
            logger.info("Recovery check: No orphan positions -- state is clean")
            return

        # DANGER: Open positions but no internal state -> orphans
        logger.critical(
            "ORPHAN POSITIONS DETECTED (%d) -- executing emergency square-off",
            len(open_positions),
        )

        tasks = []
        for pos in open_positions.values():
            close_side = Side.SELL if pos.qty > 0 else Side.BUY
            tasks.append(
                self._broker.place_market_order(
                    pos.symbol, close_side, abs(pos.qty)
                )
            )

        await asyncio.gather(*tasks)
        logger.info(
            "Emergency square-off complete -- %d positions closed",
            len(tasks),
        )
