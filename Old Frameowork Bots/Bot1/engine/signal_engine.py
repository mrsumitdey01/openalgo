"""
===============================================================================
  SIGNAL_ENGINE.PY -- Master Trigger Evaluation
  -----------------------------------------------
  Evaluates 1-minute Bank Nifty OHLCV DataFrame (with indicators
  computed in-place) against strict CANDLE CLOSE entry conditions.

  *** EXIT vs ENTRY -- TWO DIFFERENT THRESHOLDS ***

  EXIT is FAST (2 conditions):
    1. Hull BBI color changes on Bank Nifty
    2. Candle closed on the wrong side of HMA
    - In LONG  -> exit when Hull RED  + Close < HMA
    - In SHORT -> exit when Hull BLUE + Close > HMA

  ENTRY is STRICT (3 conditions, ALL must be True):
    1. Close > HMA  (price above Hull line)      [or Close < HMA for short]
    2. Hull BLUE    (HMA rising)                  [or Hull RED for short]
    3. Close > Ribbon_Max (above all 6 Fib EMAs)  [or Close < Ribbon_Min]

  The asymmetry is intentional:
    Fast exits protect capital.  Strict entries prevent false signals.
    After exit, we go FLAT and wait for re-entry conditions.
===============================================================================
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from hullbot.broker.base import Signal
from hullbot.engine.indicator_math import HullBBI, DTCRibbon

logger = logging.getLogger(__name__)


# =============================================================================
#  SIGNAL ENGINE
# =============================================================================

class SignalEngine:
    """Evaluates Bank Nifty candle data for trade signals.

    Two-tier evaluation on every 1-minute candle close:
      1. If in a position -> check EXIT (Hull color + Close vs HMA)
      2. If flat          -> check ENTRY (Hull + Close vs Ribbon boundary)
    """

    def __init__(self) -> None:
        self.hull_bbi = HullBBI()
        self.dtc_ribbon = DTCRibbon()
        self._current_position: Optional[Signal] = None

    @property
    def current_position(self) -> Optional[Signal]:
        return self._current_position

    @current_position.setter
    def current_position(self, value: Optional[Signal]) -> None:
        self._current_position = value

    # =========================================================================
    #  MAIN EVALUATION
    # =========================================================================

    def evaluate(
        self,
        bnf_df: pd.DataFrame,
        precomputed: bool = False
    ) -> Optional[Signal]:
        """Evaluate Bank Nifty and return a trade signal.

        This method MODIFIES the passed DataFrame in-place by adding
        indicator columns (hma, ribbon_max, etc.).  The caller should
        pass a copy if they need the original untouched.

        Two-tier evaluation:
          1. If in a position -> check EXIT (Hull color + Close vs HMA)
          2. If flat          -> check ENTRY (Hull + Close vs Ribbon)

        Args:
            bnf_df:   Bank Nifty 1-min OHLCV DataFrame

        Returns:
            Signal.LONG       -- Open Bull Call Spread
            Signal.SHORT      -- Open Bear Put Spread
            Signal.EXIT_LONG  -- Close Long  (Hull RED + Close < HMA)
            Signal.EXIT_SHORT -- Close Short (Hull BLUE + Close > HMA)
            None              -- No action
        """
        # -- Compute indicators --
        if not precomputed:
            try:
                bnf_df = self.hull_bbi.compute(bnf_df)
                bnf_df = self.dtc_ribbon.compute(bnf_df)
            except Exception as exc:
                logger.error(
                    "Indicator computation failed: %s", exc, exc_info=True
                )
                return None

        # -- Need at least 1 row --
        if len(bnf_df) < 1:
            logger.debug("Not enough rows -- skipping")
            return None

        # -- Extract latest completed candle --
        bnf_last = bnf_df.iloc[-1]

        # -- Guard against NaN (indicators not fully warmed up) --
        if pd.isna(bnf_last.get("hma")) or pd.isna(bnf_last.get("ribbon_max")):
            logger.debug("Indicators contain NaN -- warming up")
            return None

        # =====================================================================
        #  TIER 1: EXIT CHECK (Hull color + Close vs HMA)
        # =====================================================================
        # Two conditions for exit (BOTH must be true):
        #   1. BankNifty Hull color changed
        #   2. BankNifty candle closed on the wrong side of HMA
        #
        # LONG exit:  BNF Hull RED  +  BNF Close < BNF HMA
        # SHORT exit: BNF Hull BLUE +  BNF Close > BNF HMA

        if self._current_position == Signal.LONG:
            hull_red = bool(bnf_last["hma_bearish"])
            # Add 5-point buffer to avoid micro-flickers
            close_below_hma = float(bnf_last["close"]) < (float(bnf_last["hma"]) - 5.0)

            if hull_red and close_below_hma:
                logger.info(
                    ">>> EXIT_LONG: Hull RED + Close < HMA (with 5pt buffer) | "
                    "Close=%.2f < HMA=%.2f",
                    float(bnf_last["close"]), float(bnf_last["hma"]),
                )
                return Signal.EXIT_LONG
            elif hull_red:
                logger.debug(
                    "Hull RED but Close not 5pts below HMA -- holding"
                )

        elif self._current_position == Signal.SHORT:
            hull_blue = bool(bnf_last["hma_bullish"])
            # Add 5-point buffer to avoid micro-flickers
            close_above_hma = float(bnf_last["close"]) > (float(bnf_last["hma"]) + 5.0)

            if hull_blue and close_above_hma:
                logger.info(
                    ">>> EXIT_SHORT: Hull BLUE + Close > HMA (with 5pt buffer) | "
                    "Close=%.2f > HMA=%.2f",
                    float(bnf_last["close"]), float(bnf_last["hma"]),
                )
                return Signal.EXIT_SHORT
            elif hull_blue:
                logger.debug(
                    "Hull BLUE but Close still below HMA -- holding"
                )

        # =====================================================================
        #  TIER 2: ENTRY CHECK (Hull + DTC Strict Alignment)
        # =====================================================================
        # Only evaluated when we have NO active position (flat).
        # Requires Hull BBI direction + DTC strict Fibonacci alignment.

        if self._current_position is not None:
            return None

        # -- Evaluate full entry conditions --
        long_ok = self._check_long(bnf_last)
        short_ok = self._check_short(bnf_last)

        if long_ok:
            logger.debug(">>> SIGNAL: LONG (Hull BLUE + Close > Ribbon Max)")
            return Signal.LONG
        if short_ok:
            logger.debug(">>> SIGNAL: SHORT (Hull RED + Close < Ribbon Min)")
            return Signal.SHORT

        return None

    # =========================================================================
    #  LONG ENTRY CONDITIONS (3 checks, ALL must be True)
    # =========================================================================

    def _check_long(self, bnf) -> bool:
        """Check ALL three LONG entry conditions.

        1. Candle Close > HMA              (price above Hull line)
        2. HMA > HMA_prev                  (Hull is BLUE / rising)
        3. Candle Close > Ribbon_Max        (price above ALL 6 Fib EMAs)

        Returns True only if ALL 3 conditions are simultaneously True.
        """
        c1_close_above_hma = float(bnf["close"]) > float(bnf["hma"])
        c2_hma_bullish     = bool(bnf["hma_bullish"])
        c3_close_above_max = float(bnf["close"]) > float(bnf["ribbon_max"])

        all_met = (
            c1_close_above_hma
            and c2_hma_bullish
            and c3_close_above_max
        )

        if all_met:
            logger.debug(
                "LONG CONDITIONS MET | "
                "Close=%.2f > HMA=%.2f (BLUE) > RibbonMax=%.2f",
                bnf["close"], bnf["hma"], bnf["ribbon_max"],
            )
        else:
            logger.debug(
                "LONG check: Close>HMA=%s HullBLUE=%s Close>Max=%s",
                c1_close_above_hma, c2_hma_bullish,
                c3_close_above_max,
            )

        return all_met

    # =========================================================================
    #  SHORT ENTRY CONDITIONS (3 checks, ALL must be True)
    # =========================================================================

    def _check_short(self, bnf) -> bool:
        """Check ALL three SHORT entry conditions.

        1. Candle Close < HMA              (price below Hull line)
        2. HMA < HMA_prev                  (Hull is RED / falling)
        3. Candle Close < Ribbon_Min        (price below ALL 6 Fib EMAs)

        Returns True only if ALL 3 conditions are simultaneously True.
        """
        c1_close_below_hma = float(bnf["close"]) < float(bnf["hma"])
        c2_hma_bearish     = bool(bnf["hma_bearish"])
        c3_close_below_min = float(bnf["close"]) < float(bnf["ribbon_min"])

        all_met = (
            c1_close_below_hma
            and c2_hma_bearish
            and c3_close_below_min
        )

        if all_met:
            logger.debug(
                "SHORT CONDITIONS MET | "
                "Close=%.2f < HMA=%.2f (RED) < RibbonMin=%.2f",
                bnf["close"], bnf["hma"], bnf["ribbon_min"],
            )
        else:
            logger.debug(
                "SHORT check: Close<HMA=%s HullRED=%s Close<Min=%s",
                c1_close_below_hma, c2_hma_bearish,
                c3_close_below_min,
            )

        return all_met
