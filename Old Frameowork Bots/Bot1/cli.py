"""
===============================================================================
  MAIN.PY -- Orchestrator Event Loop
  ------------------------------------
  Boot sequence:
    1. Configure structured logging
    2. Validate config.py parameters
    3. Create broker via Factory pattern
    4. Authenticate with broker (validate access token)
    5. Initialize all components (DataStream, SignalEngine, Executor)
    6. Run state recovery (check for orphan positions)
    7. Connect WebSocket and start tick consumer
    8. Schedule hard square-off timer
    9. Run event loop until shutdown (Ctrl+C or session end)

  TIME-WINDOW ENFORCEMENT:
    09:30 -- TRADE_START:          First allowed entry
    15:10 -- NO_NEW_ENTRIES_AFTER: Block new entries (late Gamma risk)
    15:20 -- HARD_SQUARE_OFF:      Market-close ALL positions
    15:25 -- SESSION_END:          Data stream shuts down

  Shutdown sequence:
    1. Close any active spread at market
    2. Stop tick consumer task
    3. Disconnect WebSocket
    4. Exit cleanly

  Recovery design:
    On startup, the executor polls the broker's positions endpoint.
    If orphan positions exist with no matching internal state,
    they are emergency squared-off before normal operation begins.
===============================================================================
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta, time as dt_time

from hullbot import config
from hullbot.broker import get_broker
from hullbot.broker.base import Signal
from hullbot.data.data_stream import DataStreamManager
from hullbot.engine.signal_engine import SignalEngine
from hullbot.engine.options_execution import OptionsExecutionManager
from hullbot.db import state_db

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

logger = logging.getLogger("main")


# =============================================================================
#  TIME-WINDOW HELPERS (IST-localized)
# =============================================================================

def _ist_now() -> datetime:
    """Current datetime localized to Asia/Kolkata (IST)."""
    return datetime.now(IST)


def _is_in_trade_window() -> bool:
    """True if current IST time is within the ENTRY-ALLOWED window.

    Entries are allowed between TRADE_START and NO_NEW_ENTRIES_AFTER.
    Returns False before 09:30 and after 15:10.
    """
    now = _ist_now().time()
    trade_start = dt_time(config.TRADE_START_HOUR, config.TRADE_START_MINUTE)
    no_new = dt_time(config.NO_NEW_ENTRIES_HOUR, config.NO_NEW_ENTRIES_MINUTE)
    return trade_start <= now <= no_new


def _is_past_square_off() -> bool:
    """True if current IST time is at or past HARD_SQUARE_OFF."""
    now = _ist_now().time()
    square_off = dt_time(
        config.HARD_SQUARE_OFF_HOUR, config.HARD_SQUARE_OFF_MINUTE
    )
    return now >= square_off


# =============================================================================
#  TRADING BOT ORCHESTRATOR
# =============================================================================

class TradingBot:
    """Top-level orchestrator that wires all components together.

    Component ownership:
        TradingBot
         |-- broker           (BaseBroker: Fyers or Zerodha)
         |-- signal_engine    (SignalEngine: indicators + conditions)
         |-- executor         (OptionsExecutionManager: spreads + risk)
         |-- streamer         (DataStreamManager: WS -> OHLCV -> callback)
    """

    def __init__(self) -> None:
        self._broker = None
        self._streamer: DataStreamManager | None = None
        self._signal_engine: SignalEngine | None = None
        self._executor: OptionsExecutionManager | None = None
        self._shutdown_event = asyncio.Event()
        self._eod_task: asyncio.Task | None = None
        self._square_off_task: asyncio.Task | None = None
        self._reconciliation_task: asyncio.Task | None = None

    # =========================================================================
    #  MAIN ENTRY POINT
    # =========================================================================

    async def run(self) -> None:
        """Boot the full pipeline and run until shutdown."""

        # ---- 1. Configure logging ----
        self._setup_logging()

        logger.info("=" * 60)
        logger.info("  Hull BBI + DTC Fibonacci Ribbon Options Spread Bot")
        logger.info(
            "  Starting at %s",
            _ist_now().strftime("%Y-%m-%d %H:%M:%S IST"),
        )
        logger.info("=" * 60)

        # ---- 2. Validate config ----
        try:
            config.validate()
        except ValueError as exc:
            logger.critical("Config validation failed: %s", exc)
            sys.exit(1)

        # ---- 2.5 Initialize Database ----
        try:
            await state_db.init_db()
            logger.info("SQLite state database initialized (WAL mode)")
        except Exception as exc:
            logger.critical("Failed to initialize state database: %s", exc)
            sys.exit(1)

        # ---- 3. Create broker via factory ----
        try:
            self._broker = get_broker(config.ACTIVE_BROKER)
        except (ValueError, ImportError) as exc:
            logger.critical("Broker creation failed: %s", exc)
            sys.exit(1)

        # ---- 4. Authenticate ----
        try:
            await self._broker.authenticate()
        except RuntimeError as exc:
            logger.critical("Authentication failed: %s", exc)
            sys.exit(1)

        # ---- 5. Initialize components ----
        self._signal_engine = SignalEngine()
        self._executor = OptionsExecutionManager(self._broker)
        self._streamer = DataStreamManager(
            broker=self._broker,
            on_candle_callback=self._on_candle_complete,
        )

        # ---- 6. State recovery ----
        await self._executor.recover_state()

        # ---- 7. Connect WebSocket and start tick consumer ----
        try:
            await self._streamer.start()
        except Exception as exc:
            logger.critical("Failed to start data stream: %s", exc)
            sys.exit(1)

        logger.info("Bot is LIVE -- waiting for signals...")
        logger.info(
            "  Trade window:   %02d:%02d - %02d:%02d IST",
            config.TRADE_START_HOUR, config.TRADE_START_MINUTE,
            config.NO_NEW_ENTRIES_HOUR, config.NO_NEW_ENTRIES_MINUTE,
        )
        logger.info(
            "  Hard square-off: %02d:%02d IST",
            config.HARD_SQUARE_OFF_HOUR, config.HARD_SQUARE_OFF_MINUTE,
        )
        if config.PAPER_MODE:
            logger.info(
                ">>> PAPER MODE ACTIVE -- no real orders will be placed"
            )

        # ---- 8. Schedule hard square-off timer ----
        self._square_off_task = asyncio.create_task(
            self._hard_square_off_timer(),
            name="hard-square-off",
        )

        # ---- 9. Schedule EOD auto-close (fallback after square-off) ----
        self._eod_task = asyncio.create_task(
            self._eod_auto_close(),
            name="eod-auto-close",
        )

        # ---- 9.5. Start State Reconciliation Loop ----
        self._reconciliation_task = asyncio.create_task(
            self._state_reconciliation_loop(),
            name="state-reconciliation",
        )

        # ---- 10. Run until shutdown ----
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass

        # Graceful shutdown
        await self._shutdown()

    # =========================================================================
    #  CANDLE CALLBACK (fired by DataStreamManager)
    # =========================================================================

    async def _on_candle_complete(
        self,
        bnf_df,
    ) -> None:
        """Called when a 1-minute Bank Nifty candle closes.

        Processing pipeline with TIME-WINDOW ENFORCEMENT:

          Step 0: Check HARD_SQUARE_OFF time -- if past 15:20, close
                  everything and block all further processing.

          Step 1: If an active spread exists, check RISK-BASED exits
                  (P&L stop, structural stop).  These fire at ANY time
                  regardless of the trade window.

          Step 2: Check TRADE WINDOW -- block new entries before 09:30
                  or after 15:10.  Exits still allowed.

          Step 3: Evaluate the signal logic:
                  - EXIT: Hull RED + Close < HMA (2 conditions)
                  - ENTRY: Hull + DTC strict alignment + Close vs boundary

          Step 4: Execute the signal:
                  - LONG       -> Enter Bull Call Spread
                  - SHORT      -> Enter Bear Put Spread
                  - EXIT_LONG  -> Close long, go FLAT
                  - EXIT_SHORT -> Close short, go FLAT

          After exit, we wait for full re-entry conditions on next candle.
        """
        # ---- Step 0: Hard square-off check ----
        if _is_past_square_off():
            if self._executor.has_active_spread:
                logger.warning(
                    "HARD SQUARE-OFF TIME -- closing all positions"
                )
                await self._executor.close_spread()
                self._signal_engine.current_position = None
            return  # Block all processing after square-off time

        # ---- Step 1: Risk-based exits (fire at any time) ----
        if self._executor.has_active_spread:
            exited = await self._executor.check_exit_conditions(bnf_df)
            if exited:
                self._signal_engine.current_position = None
                logger.info(
                    "Position exited via risk management -- "
                    "waiting for next candle"
                )
                return  # Don't re-enter on same candle after risk exit

        # ---- Step 2: Signal evaluation ----
        # evaluate() handles exits (Hull color change) regardless of
        # trade window.  Entry signals are returned but we gate them below.
        signal = self._signal_engine.evaluate(bnf_df)

        if signal is None:
            return  # No actionable signal

        # ---- Step 3: Execute signal ----
        spot_price = float(bnf_df["close"].iloc[-1])

        # EXIT signals execute at any time (capital protection)
        if signal == Signal.EXIT_LONG:
            await self._executor.close_spread()
            self._signal_engine.current_position = None
            logger.info(
                "LONG closed (Hull RED + Close < HMA) -- "
                "waiting for re-entry conditions"
            )
            return

        if signal == Signal.EXIT_SHORT:
            await self._executor.close_spread()
            self._signal_engine.current_position = None
            logger.info(
                "SHORT closed (Hull BLUE + Close > HMA) -- "
                "waiting for re-entry conditions"
            )
            return

        # ENTRY signals are GATED by the trade window
        if not _is_in_trade_window():
            logger.debug(
                "Signal %s suppressed -- outside trade window "
                "(%02d:%02d - %02d:%02d)",
                signal.name,
                config.TRADE_START_HOUR, config.TRADE_START_MINUTE,
                config.NO_NEW_ENTRIES_HOUR, config.NO_NEW_ENTRIES_MINUTE,
            )
            return

        if signal == Signal.LONG:
            success = await self._executor.execute_bull_call_spread(
                spot_price, bnf_df
            )
            if success:
                self._signal_engine.current_position = Signal.LONG

        elif signal == Signal.SHORT:
            success = await self._executor.execute_bear_put_spread(
                spot_price, bnf_df
            )
            if success:
                self._signal_engine.current_position = Signal.SHORT

    # =========================================================================
    #  HARD SQUARE-OFF TIMER (15:20 IST)
    # =========================================================================

    async def _hard_square_off_timer(self) -> None:
        """Background task that fires at HARD_SQUARE_OFF time.

        At 15:20 IST, instantly market-sells ALL open positions to
        preempt broker RMS auto-liquidation at 15:25+.

        This is a separate timer from EOD auto-close because:
        - Square-off is AGGRESSIVE (market orders, immediate)
        - EOD auto-close is a FALLBACK (in case square-off missed something)
        """
        try:
            while not self._shutdown_event.is_set():
                now = _ist_now()
                target = now.replace(
                    hour=config.HARD_SQUARE_OFF_HOUR,
                    minute=config.HARD_SQUARE_OFF_MINUTE,
                    second=0, microsecond=0,
                )

                if now >= target:
                    # If we missed it for today, schedule for tomorrow
                    target += timedelta(days=1)
                
                wait_seconds = (target - now).total_seconds()
                logger.info(
                    "Hard square-off scheduled at %02d:%02d IST (in %.0f min)",
                config.HARD_SQUARE_OFF_HOUR,
                config.HARD_SQUARE_OFF_MINUTE,
                wait_seconds / 60,
            )

            await asyncio.sleep(wait_seconds)
            await self._execute_square_off()

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(
                "Hard square-off timer error: %s", exc, exc_info=True
            )

    async def _execute_square_off(self) -> None:
        """Execute the hard square-off: close all positions at market."""
        logger.info("=" * 60)
        logger.info("  HARD SQUARE-OFF @ %02d:%02d IST",
                     config.HARD_SQUARE_OFF_HOUR,
                     config.HARD_SQUARE_OFF_MINUTE)
        logger.info("=" * 60)

        if self._executor is not None and self._executor.has_active_spread:
            logger.info(
                "Closing active %s spread at MARKET",
                self._executor.active_spread.spread_type.value,
            )
            await self._executor.close_spread()
            self._signal_engine.current_position = None
            logger.info("Hard square-off complete -- all positions closed")
        else:
            logger.info("No active positions at square-off time")

    # =========================================================================
    #  EOD AUTO-CLOSE (fallback safety net)
    # =========================================================================

    async def _eod_auto_close(self) -> None:
        """Fallback background task at SESSION_END (15:25 IST).

        This fires AFTER the hard square-off (15:20) as a safety net.
        If the square-off somehow missed a position, this catches it.
        """
        try:
            while not self._shutdown_event.is_set():
                now = _ist_now()
                eod = now.replace(
                    hour=config.SESSION_END_HOUR,
                    minute=config.SESSION_END_MINUTE,
                    second=0, microsecond=0,
                )

                if now >= eod:
                    # Next day
                    eod += timedelta(days=1)

                wait_seconds = (eod - now).total_seconds()
                logger.info(
                    "EOD auto-close scheduled at %02d:%02d IST (in %.0f min)",
                config.SESSION_END_HOUR, config.SESSION_END_MINUTE,
                wait_seconds / 60,
            )

            await asyncio.sleep(wait_seconds)

            logger.info("=" * 60)
            logger.info("  SESSION END -- EOD AUTO-CLOSE (FALLBACK)")
            logger.info("=" * 60)

            if self._executor is not None and self._executor.has_active_spread:
                logger.info(
                    "Closing active %s spread at market (fallback)",
                    self._executor.active_spread.spread_type.value,
                )
                await self._executor.close_spread()
                self._signal_engine.current_position = None
                logger.info("EOD spread closed successfully")
            else:
                logger.info("No active spread at session end -- all clear")

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(
                "EOD auto-close error: %s", exc, exc_info=True
            )

    # =========================================================================
    #  STATE RECONCILIATION
    # =========================================================================

    async def _state_reconciliation_loop(self) -> None:
        """Background task that runs every 30s to detect and fix state desyncs.
        
        Uses non-blocking REST calls to compare actual broker positions
        against internal bot memory.
        """
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(30)
                
                if self._broker is None or self._executor is None:
                    continue

                if self._executor.is_executing:
                    logger.debug("Reconciliation skipped: executor is actively building/closing spread.")
                    continue

                try:
                    positions = await self._broker.get_positions()
                except Exception as exc:
                    logger.error("Reconciliation fetch failed: %s", exc)
                    continue

                if self._executor.is_executing:
                    logger.debug("Reconciliation aborted mid-flight: executor started building/closing spread.")
                    continue

                open_positions = [p for p in positions if p.qty != 0]

                # Case 1: Bot thinks it's active, but broker says Flat (manually closed/SL hit)
                if not open_positions and self._executor.has_active_spread:
                    logger.critical(
                        "DESYNC ALERT: Broker shows FLAT but internal state is ACTIVE. "
                        "Clearing internal memory and DB!"
                    )
                    
                    spread = self._executor.active_spread
                    if spread and spread.db_row_id != -1:
                        asyncio.create_task(state_db.mark_closed(spread.db_row_id))

                    self._executor._active_spread = None
                    if self._signal_engine is not None:
                        self._signal_engine.current_position = None

                # Case 2: Bot thinks it's flat, but broker shows open positions (Ghost trades)
                elif open_positions and not self._executor.has_active_spread:
                    logger.critical(
                        "DESYNC ALERT: Broker shows OPEN positions but internal state is FLAT. "
                        "Executing emergency square-off!"
                    )
                    await self._executor.recover_state()

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("State reconciliation loop crashed: %s", exc, exc_info=True)

    # =========================================================================
    #  SHUTDOWN
    # =========================================================================

    async def _shutdown(self) -> None:
        """Graceful shutdown: close positions, cancel tasks, disconnect."""
        logger.info("Initiating graceful shutdown...")

        # Cancel background timers
        for task in (self._square_off_task, self._eod_task, self._reconciliation_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close any active spread at market
        if self._executor is not None and self._executor.has_active_spread:
            logger.info("Closing active spread before shutdown")
            await self._executor.close_spread()

        # Stop data stream (cancels consumer task, disconnects WS)
        if self._streamer is not None:
            await self._streamer.stop()

        logger.info("Shutdown complete")

    def request_shutdown(self) -> None:
        """Thread-safe method to request bot shutdown."""
        self._shutdown_event.set()

    # =========================================================================
    #  LOGGING
    # =========================================================================

    @staticmethod
    def _setup_logging() -> None:
        """Configure structured logging for all modules."""
        logging.basicConfig(
            level=config.LOG_LEVEL,
            format=config.LOG_FORMAT,
            datefmt=config.LOG_DATEFMT,
        )
        # Reduce noise from third-party libraries
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("websocket").setLevel(logging.WARNING)
        logging.getLogger("fyers_apiv3").setLevel(logging.WARNING)


# =============================================================================
#  ENTRY POINT
# =============================================================================

async def main() -> None:
    """Create and run the TradingBot."""
    bot = TradingBot()

    loop = asyncio.get_running_loop()
    try:
        import signal as _signal
        for sig in (_signal.SIGINT, _signal.SIGTERM):
            loop.add_signal_handler(sig, bot.request_shutdown)
    except (NotImplementedError, AttributeError):
        pass

    try:
        await bot.run()
    except KeyboardInterrupt:
        bot.request_shutdown()
        await bot._shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown via Ctrl+C")
