"""
===============================================================================
  DATA_STREAM.PY -- Async Tick Ingestion & OHLCV Resampling
  ---------------------------------------------------------
  Architecture:

    [Broker WebSocket]           (runs on SDK thread)
           |
           v
    loop.call_soon_threadsafe()  (bridge to asyncio)
           |
           v
    [asyncio.Queue]              (capacity: 10,000 ticks)
           |
           v
    tick_consumer()              (persistent async task)
      |
      v
     BankNifty                    (TickResampler)
     Resampler
      |
     1-min OHLCV DataFrame        (rolling 100 candles)
      |
      v
    on_candle_callback()         (triggers signal evaluation)

  The tick consumer NEVER runs indicator math -- it only resamples.
  This prevents the WebSocket queue from backing up.
===============================================================================
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional
from collections import deque

import pandas as pd

from hullbot import config
from hullbot.broker.base import BaseBroker, TickData

logger = logging.getLogger(__name__)

# IST timezone offset (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


# =============================================================================
#  TICK RESAMPLER
# =============================================================================

class TickResampler:
    """Converts raw ticks into 1-minute OHLCV candles.

    One instance per instrument (BankNifty).
    Accumulates ticks within each clock-minute boundary, then emits a
    completed candle when the next minute begins.

    Volume handling:
      Broker ticks report CUMULATIVE daily volume.  We compute per-candle
      volume as the delta between the last and first tick in each minute.
      If the delta is negative (market open reset), we use the raw value.
    """

    def __init__(self, symbol: str, max_candles: int = 100) -> None:
        self._symbol = symbol
        self._max_candles = max_candles

        # Current minute being accumulated (Unix epoch floored to minute)
        self._current_minute: Optional[int] = None

        # Current candle accumulation state
        self._candle_open: float = 0.0
        self._candle_high: float = 0.0
        self._candle_low: float = float("inf")
        self._candle_close: float = 0.0
        self._candle_vol: int = 0
        self._last_known_vol: int = 0
        self._tick_count: int = 0

        # Completed candle storage
        self._candles: deque[dict] = deque(maxlen=max_candles)
        self._df = pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

    # -- Public Properties ---------------------------------------------------

    @property
    def df(self) -> pd.DataFrame:
        """Rolling OHLCV DataFrame of completed candles."""
        return self._df

    @property
    def candle_count(self) -> int:
        """Number of completed candles available."""
        return len(self._candles)

    @property
    def is_warmed_up(self) -> bool:
        """True when enough candles exist for indicator computation.

        Requires at least max(EMA_LENGTHS) candles so the slowest EMA
        (EMA-60) has meaningful values from the start.
        """
        return self.candle_count >= max(config.EMA_LENGTHS)

    # -- Tick Processing -----------------------------------------------------

    def on_tick(self, tick: TickData) -> bool:
        """Process a single tick.

        Returns:
            True  -- a new 1-minute candle was completed (minute boundary
                     crossed).  The caller should check the updated DataFrame.
            False -- tick was accumulated into the current in-progress candle.
        """
        minute = self._floor_to_minute(tick.timestamp)

        # Calculate volume delta continuously
        if self._last_known_vol == 0:
            vol_delta = 0  # First tick ever, don't dump daily volume into it
        elif tick.volume < self._last_known_vol:
            vol_delta = tick.volume  # Reset
        else:
            vol_delta = tick.volume - self._last_known_vol
            
        self._last_known_vol = tick.volume

        # First tick ever received
        if self._current_minute is None:
            self._current_minute = minute
            self._start_candle(tick, vol_delta)
            return False

        # Same minute -- update current candle
        if minute == self._current_minute:
            self._update_candle(tick, vol_delta)
            return False

        # New minute -- close the previous candle, start a new one
        self._close_candle()
        self._current_minute = minute
        self._start_candle(tick, vol_delta)
        return True  # Signal that a candle was completed

    # -- Private Candle Lifecycle -------------------------------------------

    def _start_candle(self, tick: TickData, vol_delta: int) -> None:
        """Begin a new candle with the first tick of a minute."""
        self._candle_open = tick.ltp
        self._candle_high = tick.ltp
        self._candle_low = tick.ltp
        self._candle_close = tick.ltp
        self._candle_vol = vol_delta
        self._tick_count = 1

    def _update_candle(self, tick: TickData, vol_delta: int) -> None:
        """Update the in-progress candle with a new tick."""
        self._candle_high = max(self._candle_high, tick.ltp)
        self._candle_low = min(self._candle_low, tick.ltp)
        self._candle_close = tick.ltp
        self._candle_vol += vol_delta
        self._tick_count += 1

    def _close_candle(self) -> None:
        """Finalize the current candle and append to history."""
        if self._tick_count == 0:
            return  # No ticks accumulated (shouldn't happen in practice)

        candle = {
            "timestamp": self._current_minute,
            "open":      self._candle_open,
            "high":      self._candle_high,
            "low":       self._candle_low,
            "close":     self._candle_close,
            "volume":    self._candle_vol,
        }

        self._candles.append(candle)
        self._df = pd.DataFrame(self._candles)

        logger.debug(
            "%s candle | O=%.2f H=%.2f L=%.2f C=%.2f V=%d [%d total]",
            self._symbol,
            candle["open"], candle["high"], candle["low"],
            candle["close"], candle["volume"],
            len(self._candles),
        )

    @staticmethod
    def _floor_to_minute(timestamp: float) -> int:
        """Floor a Unix timestamp to the start of its containing minute."""
        return int(timestamp) // 60 * 60


# =============================================================================
#  DATA STREAM MANAGER
# =============================================================================

class DataStreamManager:
    """Orchestrates tick ingestion, OHLCV resampling, and signal callbacks.

    Owns the asyncio.Queue that bridges the broker WebSocket thread to
    the async processing pipeline.  When a Bank Nifty 1-minute candle
    closes, fires the callback with all three DataFrames.
    """

    def __init__(
        self,
        broker: BaseBroker,
        on_candle_callback: Callable,
    ) -> None:
        """
        Args:
            broker:             Authenticated BaseBroker instance.
            on_candle_callback: Async callable(bnf_df)
                                invoked when a Bank Nifty candle closes.
        """
        self._broker = broker
        self._on_candle_callback = on_candle_callback

        # Shared tick queue: WS thread pushes, async consumer pulls
        self._queue: asyncio.Queue[TickData] = asyncio.Queue(
            maxsize=config.TICK_QUEUE_MAX_SIZE
        )

        # One resampler per monitored instrument
        self._resamplers: dict[str, TickResampler] = {
            config.SYM_BANKNIFTY: TickResampler(
                config.SYM_BANKNIFTY, config.OHLCV_ROLLING_WINDOW
            ),
        }

        # Consumer task handle
        self._consumer_task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def resamplers(self) -> dict[str, TickResampler]:
        """Access the TickResampler instances (for inspection/testing)."""
        return self._resamplers

    # -- Tick Callback (called from event loop thread) -----------------------

    def _on_tick(self, tick: TickData) -> None:
        """Callback for broker WebSocket ticks.

        Called on the asyncio event loop thread (bridged from the WS
        thread by the broker client via loop.call_soon_threadsafe).
        Pushes the tick into the queue.

        If the queue is full, drops the OLDEST tick to prevent
        backpressure from stalling the WebSocket connection.
        """
        try:
            self._queue.put_nowait(tick)
        except asyncio.QueueFull:
            # Drop oldest tick to make room
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(tick)
            except asyncio.QueueFull:
                logger.warning(
                    "Tick queue overflow -- dropping tick for %s", tick.symbol
                )

    # -- Lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Connect broker WebSocket and start the tick consumer task."""
        self._running = True

        # Build subscription list from config (broker-agnostic)
        symbols = config.get_subscription_symbols()

        # Connect WebSocket with our tick callback
        await self._broker.connect_websocket(
            symbols=symbols,
            on_tick=self._on_tick,
        )

        # Start the persistent async consumer task
        self._consumer_task = asyncio.create_task(
            self._tick_consumer(),
            name="tick-consumer",
        )

        logger.info(
            "DataStreamManager started -- consuming ticks for %d instruments",
            len(self._resamplers),
        )

    async def stop(self) -> None:
        """Stop the tick consumer and disconnect WebSocket."""
        self._running = False

        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        await self._broker.disconnect_websocket()
        logger.info("DataStreamManager stopped")

    # -- Tick Consumer (persistent async task) --------------------------------

    async def _tick_consumer(self) -> None:
        """Pulls ticks from the queue, routes to the correct resampler.

        When a 1-minute candle completes for Bank Nifty (the primary
        signal instrument), fires the on_candle_callback with copies
        of all DataFrames.

        Uses asyncio.wait_for with a 5-second timeout to periodically
        check the self._running flag even if no ticks arrive.
        """
        logger.info("Tick consumer started")

        while self._running:
            # -- Pull next tick (with timeout for shutdown checking) --
            try:
                # Wait for the first tick (yielding control to event loop)
                first_tick = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue    # No ticks for 5s -- loop and check _running
            except asyncio.CancelledError:
                break

            # Drain remaining pending ticks synchronously
            ticks = [first_tick]
            while not self._queue.empty():
                try:
                    ticks.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Process the batch sequentially
            for tick in ticks:
                # -- Resolve broker symbol -> canonical key --
                canonical = config.get_canonical_symbol(tick.symbol)
                if canonical is None:
                    continue    # Unknown symbol -- skip

                resampler = self._resamplers.get(canonical)
                if resampler is None:
                    continue

                # -- Feed tick to resampler --
                candle_completed = resampler.on_tick(tick)

                # -- Trigger evaluation when Bank Nifty candle closes --
                if candle_completed and canonical == config.SYM_BANKNIFTY:
                    await self._handle_candle_close()

        logger.info("Tick consumer stopped")

    async def _handle_candle_close(self) -> None:
        """Called when a Bank Nifty 1-minute candle closes.

        Checks session hours, warmup state, and then fires the
        callback with copies of all OHLCV DataFrames.
        """
        # -- Session window check --
        if not self._in_session():
            return

        # -- Warmup check --
        # All resamplers must have enough candles for indicator computation
        if not all(r.is_warmed_up for r in self._resamplers.values()):
            bnf_cnt = self._resamplers[config.SYM_BANKNIFTY].candle_count
            logger.info(
                "Indicators warming up -- BNF:%d candles "
                "(need %d)",
                bnf_cnt, max(config.EMA_LENGTHS),
            )
            return

        # -- Get DataFrame copy (so indicator computation doesn't
        #    mutate the resampler's internal data) --
        bnf_df = self._resamplers[config.SYM_BANKNIFTY].df.copy()

        # -- Fire callback --
        try:
            await self._on_candle_callback(bnf_df)
        except Exception as exc:
            logger.error(
                "Error in candle callback: %s", exc, exc_info=True
            )

    def _in_session(self) -> bool:
        """Check if current IST time is within the trading session window.

        Returns True if SESSION_START <= now <= SESSION_END.
        """
        now = datetime.now(IST)
        start = now.replace(
            hour=config.SESSION_START_HOUR,
            minute=config.SESSION_START_MINUTE,
            second=0, microsecond=0,
        )
        end = now.replace(
            hour=config.SESSION_END_HOUR,
            minute=config.SESSION_END_MINUTE,
            second=0, microsecond=0,
        )
        return start <= now <= end
