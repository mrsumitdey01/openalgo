"""
bot6/config.py
==============
All configurable parameters for Bot6 DTC Intraday Strategy.
Edit this file to tune the strategy without touching core logic.
"""

# --------------------------------------------------------------------------- #
# DTC INDICATOR PARAMETERS (EMA Ribbon)
# These map directly to the Pine Script range inputs:
#   r1_start=8,  r1_end=13
#   r2_start=21, r2_end=26
#   r3_start=34, r3_end=40
# --------------------------------------------------------------------------- #
EMA_LENGTHS: list[int] = [8, 13, 21, 26, 34, 40]

# --------------------------------------------------------------------------- #
# CAPITAL & LEVERAGE
# --------------------------------------------------------------------------- #
CAPITAL_PER_TRADE: float = 50_000.0   # Rs allocated capital per trade
LEVERAGE: int = 5                      # Broker intraday leverage (5x)
MAX_EXPOSURE: float = CAPITAL_PER_TRADE * LEVERAGE  # Rs 2,50,000

# --------------------------------------------------------------------------- #
# RISK MANAGEMENT — "TRIGGER AND TRAIL" LOGIC
#
# INITIAL_SL_PCT       : Hard stop loss distance from entry (0.3%)
#                        Active from bar 1. If hit before trail activates → full loss.
#
# TRAIL_ACTIVATION_PCT : The profit level at which the trailing stop ACTIVATES (0.3%).
#                        Below this profit, only the hard SL protects the position.
#                        At this level: SL is immediately bumped to BREAKEVEN (entry).
#
# TRAIL_PCT            : Once active, the SL trails this % behind the running peak (0.3%).
#                        It NEVER moves backward.
#
# TARGET_PCT           : Hard max-profit square-off. Position closes immediately at +1.0%.
#                        This is a ceiling — no further trailing above this level.
#
# Summary for a LONG at Rs.1000:
#   Hard SL          = 997.00  (active immediately)
#   Trail activates  = 1003.00 (+0.3% profit trigger)
#   SL on activation = 1000.00 (moves to breakeven)
#   Trail at peak    = peak * (1 - 0.003)  e.g., if peak=1006 → SL=1002.98
#   Hard Target      = 1010.00 (+1.0% — exit immediately)
# --------------------------------------------------------------------------- #
TARGET_PCT: float = 0.010            # 1.0% hard max-profit target
INITIAL_SL_PCT: float = 0.003        # 0.3% hard initial stop loss
TRAIL_ACTIVATION_PCT: float = 0.003  # 0.3% profit required to activate trailing stop
TRAIL_PCT: float = 0.003             # 0.3% trailing distance once active

# --------------------------------------------------------------------------- #
# TIME FENCES (all times in 24-hr HH:MM format, IST)
# --------------------------------------------------------------------------- #
MARKET_START: str = "09:15"      # No entries before this time
CUTOFF_TIME: str = "14:45"       # No NEW entries after this time
SQUARE_OFF_TIME: str = "15:15"   # Hard square-off — market order all open positions

# --------------------------------------------------------------------------- #
# LOGGING
# --------------------------------------------------------------------------- #
LOG_FILE: str = "bot6_trades.log"
TRADE_CSV: str = "bot6_tradelog.csv"
