"""
═══════════════════════════════════════════════════════════════════════════════
  CONFIG.PY — Hull BBI + DTC Ribbon Options Spread Bot
  ─────────────────────────────────────────────────────
  Central configuration.  Every tunable parameter lives here.
  No magic numbers scattered across other modules.

  Credentials can be set directly below OR via environment variables
  (env vars take precedence when present).
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import logging

# ─────────────────────────────────────────────────────────────────────────────
#  BROKER SELECTION & MODE
# ─────────────────────────────────────────────────────────────────────────────
ACTIVE_BROKER: str = "FYERS"        # "FYERS" | "ZERODHA"
PAPER_MODE: bool = True             # True → logs every order, never executes

# ─────────────────────────────────────────────────────────────────────────────
#  FYERS API V3 CREDENTIALS
#  ─────────────────────────
#  Dashboard: https://myapi.fyers.in/dashboard
#  Access token is valid for ONE trading session (generate daily).
# ─────────────────────────────────────────────────────────────────────────────
FYERS_APP_ID: str = os.getenv("FYERS_APP_ID", "FFSTJBS5TJ-100")
FYERS_SECRET_KEY: str = os.getenv("FYERS_SECRET_KEY", "0G6IL2F489")
FYERS_REDIRECT_URI: str = os.getenv("FYERS_REDIRECT_URI", "https://127.0.0.1:8080/")
FYERS_ACCESS_TOKEN: str = os.getenv("FYERS_ACCESS_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOlsiZDoxIiwiZDoyIiwieDowIiwieDoxIiwieDoyIl0sImF0X2hhc2giOiJnQUFBQUFCcUl1ZHgyUW4xTzZyZXlUYTRNaEZLVmszZW5JRnMzN1hmM2pULUUyQTM4OHZXaWhUZGoxQlVyZnBpLU9UcUFZQmNnZk5fZnBUeU52eUdTYVBFSkVsVXZvTWxIMVpwOGtkX0JYUU5abEZxVWQ5cjF3az0iLCJkaXNwbGF5X25hbWUiOiIiLCJvbXMiOiJLMSIsImhzbV9rZXkiOiI0YzZkZjM4MDQwODQ5OWRmMjdhMWRkNzVkYzBmZDQyNDIwZmRmOGJjYjZmMDJhMTRhNGY1ZTlkNyIsImlzRGRwaUVuYWJsZWQiOiJOIiwiaXNNdGZFbmFibGVkIjoiTiIsImZ5X2lkIjoiWFMwNjE2NyIsImFwcFR5cGUiOjEwMCwiZXhwIjoxNzgwNzA1ODAwLCJpYXQiOjE3ODA2NzIzNjksImlzcyI6ImFwaS5meWVycy5pbiIsIm5iZiI6MTc4MDY3MjM2OSwic3ViIjoiYWNjZXNzX3Rva2VuIn0.PdQVvRis0aiYhixn6iS5tNY-iZ6gQ81xnzf-Q1CezJg")

# ─────────────────────────────────────────────────────────────────────────────
#  ZERODHA KITECONNECT CREDENTIALS
#  ────────────────────────────────
#  Portal: https://kite.trade/
#  Requires browser-based login → request_token → access_token each session.
# ─────────────────────────────────────────────────────────────────────────────
ZERODHA_API_KEY: str = os.getenv("ZERODHA_API_KEY", "YOUR_ZERODHA_API_KEY")
ZERODHA_API_SECRET: str = os.getenv("ZERODHA_API_SECRET", "YOUR_ZERODHA_SECRET")
ZERODHA_ACCESS_TOKEN: str = os.getenv("ZERODHA_ACCESS_TOKEN", "")

# ─────────────────────────────────────────────────────────────────────────────
#  INSTRUMENTS — FYERS SYMBOL FORMAT
#  ──────────────────────────────────
#  Fyers uses exchange-prefixed strings: "NSE:SYMBOL"
#  These 3 instruments are used for signal generation & verification.
# ─────────────────────────────────────────────────────────────────────────────
FYERS_BANKNIFTY_SPOT: str = "NSE:NIFTY50-INDEX"   # Nifty Index (signal)
FYERS_OPTION_EXCHANGE: str = "NSE"                    # Options listed under NSE

# ─────────────────────────────────────────────────────────────────────────────
#  INSTRUMENTS — ZERODHA FORMAT
#  ────────────────────────────
#  KiteTicker requires integer instrument_tokens for WebSocket subscriptions.
#  Get tokens via kite.instruments("NSE") / kite.instruments("NFO").
#  The values below are common defaults — verify against live instrument dump.
# ─────────────────────────────────────────────────────────────────────────────
ZERODHA_BANKNIFTY_TOKEN: int = 256265       # Nifty 50 Index
ZERODHA_BANKNIFTY_SYMBOL: str = "NIFTY 50"
ZERODHA_OPTION_EXCHANGE: str = "NFO"        # Options on NFO exchange

# ─────────────────────────────────────────────────────────────────────────────
#  CANONICAL SYMBOL KEYS
#  ─────────────────────
#  Internal identifiers used by data_stream & signal_engine
#  to route ticks to the correct OHLCV resampler.
# ─────────────────────────────────────────────────────────────────────────────
SYM_BANKNIFTY: str = "NIFTY"
SYM_CRUDEOIL: str = "CRUDEOIL"
SYM_GOLDM: str = "GOLDM"

# Map canonical keys → Fyers symbols (used by data_stream to build the
# subscription list and to route incoming ticks)
FYERS_SYMBOL_MAP: dict[str, str] = {
    SYM_BANKNIFTY: FYERS_BANKNIFTY_SPOT,
    SYM_CRUDEOIL: "MCX:CRUDEOIL26JULFUT", # Placeholder
    SYM_GOLDM: "MCX:GOLDM26JULFUT",       # Placeholder
}

# Reverse lookup: Fyers symbol → canonical key
FYERS_REVERSE_MAP: dict[str, str] = {v: k for k, v in FYERS_SYMBOL_MAP.items()}

# Map canonical keys → Zerodha instrument tokens
ZERODHA_TOKEN_MAP: dict[str, int] = {
    SYM_BANKNIFTY: ZERODHA_BANKNIFTY_TOKEN,
    SYM_CRUDEOIL: 111111, # Placeholder
    SYM_GOLDM: 222222,    # Placeholder
}

# Reverse lookup: Zerodha token → canonical key
ZERODHA_TOKEN_REVERSE_MAP: dict[int, str] = {
    v: k for k, v in ZERODHA_TOKEN_MAP.items()
}

# ─────────────────────────────────────────────────────────────────────────────
#  INDICATOR PARAMETERS
#  ────────────────────
#  Hull BBI:    Hull Moving Average with WMA nesting (Length 21)
#  DTC Ribbon:  6-line Fibonacci EMA cluster
#               Synergy: EMA 21 mirrors the Hull BBI 21 lookback.
#               Leading edges (8, 13) front-run momentum.
#               Anchor (40) provides structural support.
# ─────────────────────────────────────────────────────────────────────────────
HMA_LENGTH: int = 21                                # Hull MA lookback
EMA_LENGTHS: list[int] = [8, 13, 21, 26, 34, 40]   # DTC Fibonacci Ribbon

# ─────────────────────────────────────────────────────────────────────────────
#  OPTIONS PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
LOT_SIZE: int = 25              # Nifty options lot size
LOT_MULTIPLIER: int = 1         # Number of lots per leg (1 for testing, increase for live)
SPREAD_WIDTH: int = 150         # Points between ATM buy leg and OTM sell leg
STRIKE_INTERVAL: int = 50       # Nifty strikes are at 50-point intervals

# The underlying name used in option symbol construction
# Underlying string. Supported indices can be switched seamlessly (e.g. "BANKNIFTY" <-> "NIFTY")
# The Fyers/Zerodha translation dictionaries will handle exact symbol mapping under the hood.
OPTION_UNDERLYING: str = "BANKNIFTY"

# ─────────────────────────────────────────────────────────────────────────────
#  EXECUTION PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
LIMIT_OFFSET_POINTS: float = 2.0    # Points above/below LTP for limit orders
LEG_FILL_TIMEOUT_SECS: float = 5.0  # Max wait per spread leg to fill
MARKET_FALLBACK_TIMEOUT: float = 3.0 # Wait for market-order fallback fill

# Limit Chasing Config (Entry Slippage Control)
# BankNifty Parameters
BNF_CHASE_MAX_SLIPPAGE_POINTS: float = 3.00
BNF_CHASE_INTERVAL_SECS: float = 1.5
BNF_CHASE_STEP_POINTS: float = 0.15
BNF_CHASE_MAX_RETRIES: int = 20

# Nifty 50 Parameters
NIFTY_CHASE_MAX_SLIPPAGE_POINTS: float = 1.50
NIFTY_CHASE_INTERVAL_SECS: float = 1.0
NIFTY_CHASE_STEP_POINTS: float = 0.10
NIFTY_CHASE_MAX_RETRIES: int = 15

# ─────────────────────────────────────────────────────────────────────────────
#  TIME-WINDOW ENFORCEMENT (IST)
#  ─────────────────────────────
#  Options scalping relies on institutional liquidity.  These blocks
#  prevent trading during low-volume chop, erratic opens, and late-day
#  gamma spikes.
#
#  TRADE_START:         Block all entries before this time.
#                       Lets gap-up/down math stabilize after open.
#
#  NO_NEW_ENTRIES_AFTER: Block new trades after this time.
#                       Avoids late-day Gamma spikes and low liquidity.
#
#  HARD_SQUARE_OFF:     Instantly market-sell all open positions.
#                       Preempts broker RMS auto-liquidation at 15:25+.
#
#  SESSION_END:         Data stream stops firing callbacks.
# ─────────────────────────────────────────────────────────────────────────────
SESSION_START_HOUR: int = 9
SESSION_START_MINUTE: int = 30

# Trade window (entries only allowed between these times)
TRADE_START_HOUR: int = 9
TRADE_START_MINUTE: int = 30

NO_NEW_ENTRIES_HOUR: int = 14
NO_NEW_ENTRIES_MINUTE: int = 45

# Hard square-off (close ALL positions at market)
HARD_SQUARE_OFF_HOUR: int = 15
HARD_SQUARE_OFF_MINUTE: int = 15

# Session end (stop data processing)
SESSION_END_HOUR: int = 15
SESSION_END_MINUTE: int = 25

# ─────────────────────────────────────────────────────────────────────────────
#  EXIT / RISK PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
# 1. Spread P&L Stop: if the spread loses this % of its initial cost → square off
#    Example: spread cost ₹5,000 → exit if P&L drops to -₹750 (15%)
SPREAD_STOP_LOSS_PCT: float = 0.15

# 2. Spot Structural Stop: lookback in 1-minute candles
#    LONG  → exit if BankNifty spot closes below Lowest-Low of last N candles
#    SHORT → exit if BankNifty spot closes above Highest-High of last N candles
STRUCTURAL_STOP_LOOKBACK: int = 5

# ─────────────────────────────────────────────────────────────────────────────
#  RECOVERY / RECONNECTION
# ─────────────────────────────────────────────────────────────────────────────
RECONNECT_MAX_RETRIES: int = 5
RECONNECT_BASE_DELAY_SECS: float = 3.0   # Exponential backoff: delay * 2^attempt

# ─────────────────────────────────────────────────────────────────────────────
#  DATA PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
TICK_QUEUE_MAX_SIZE: int = 10_000   # asyncio.Queue capacity
OHLCV_ROLLING_WINDOW: int = 100     # Keep last N 1-min candles in memory
                                     # (must be ≥ max(EMA_LENGTHS) for warmup)

# ─────────────────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────────────────
LOG_LEVEL: int = logging.INFO
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s"
LOG_DATEFMT: str = "%Y-%m-%d %H:%M:%S"


# ─────────────────────────────────────────────────────────────────────────────
#  BROKER-AGNOSTIC HELPERS
#  ────────────────────────
#  These functions let data_stream.py work identically regardless of
#  which broker is active.  No module outside config.py should reference
#  FYERS_SYMBOL_MAP or ZERODHA_TOKEN_MAP directly.
# ─────────────────────────────────────────────────────────────────────────────

def get_subscription_symbols() -> list:
    """Return the WebSocket subscription list for the active broker.

    Fyers:   List of string symbols  ["NSE:NIFTYBANK-INDEX", ...]
    Zerodha: List of integer tokens   [260105, ...]
    """
    if ACTIVE_BROKER == "FYERS":
        return list(FYERS_SYMBOL_MAP.values())
    elif ACTIVE_BROKER == "ZERODHA":
        return list(ZERODHA_TOKEN_MAP.values())
    raise ValueError(f"Unknown broker: {ACTIVE_BROKER}")


def get_canonical_symbol(broker_symbol) -> str | None:
    """Map a broker-specific tick symbol back to its canonical key.

    Args:
        broker_symbol: Fyers string (e.g. "NSE:NIFTYBANK-INDEX")
                       or Zerodha int/str token (e.g. 260105)

    Returns:
        Canonical key ("BANKNIFTY") or None if unknown.
    """
    if ACTIVE_BROKER == "FYERS":
        return FYERS_REVERSE_MAP.get(str(broker_symbol))
    elif ACTIVE_BROKER == "ZERODHA":
        # Zerodha tokens may arrive as int or string depending on SDK version
        token = int(broker_symbol) if not isinstance(broker_symbol, int) else broker_symbol
        return ZERODHA_TOKEN_REVERSE_MAP.get(token)
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  SELF-VALIDATION
#  ────────────────
#  Running `python config.py` directly will validate critical params.
# ─────────────────────────────────────────────────────────────────────────────
def validate() -> None:
    """Validate critical configuration parameters at startup."""
    errors: list[str] = []

    if ACTIVE_BROKER not in ("FYERS", "ZERODHA"):
        errors.append(f"ACTIVE_BROKER must be 'FYERS' or 'ZERODHA', got '{ACTIVE_BROKER}'")

    if OHLCV_ROLLING_WINDOW < max(EMA_LENGTHS):
        errors.append(
            f"OHLCV_ROLLING_WINDOW ({OHLCV_ROLLING_WINDOW}) must be ≥ "
            f"max(EMA_LENGTHS) ({max(EMA_LENGTHS)}) for indicator warmup"
        )

    if SPREAD_WIDTH % STRIKE_INTERVAL != 0:
        errors.append(
            f"SPREAD_WIDTH ({SPREAD_WIDTH}) must be a multiple of "
            f"STRIKE_INTERVAL ({STRIKE_INTERVAL})"
        )

    if LOT_MULTIPLIER < 1:
        errors.append(f"LOT_MULTIPLIER must be ≥ 1, got {LOT_MULTIPLIER}")

    if STRUCTURAL_STOP_LOOKBACK < 1:
        errors.append(f"STRUCTURAL_STOP_LOOKBACK must be ≥ 1, got {STRUCTURAL_STOP_LOOKBACK}")

    if errors:
        raise ValueError("Config validation failed:\n  - " + "\n  - ".join(errors))

    print("[OK] Config validation passed")
    print(f"  Broker:       {ACTIVE_BROKER}")
    print(f"  Paper Mode:   {PAPER_MODE}")
    print(f"  Underlying:   {OPTION_UNDERLYING}")
    print(f"  Lot Size:     {LOT_SIZE} x {LOT_MULTIPLIER} = {LOT_SIZE * LOT_MULTIPLIER} per leg")
    print(f"  Spread Width: {SPREAD_WIDTH} pts")

# ─────────────────────────────────────────────────────────────────────────────
#  COMMODITY OVERRIDES
# ─────────────────────────────────────────────────────────────────────────────
# If an underlying is selected, override the time windows, lots, and exchange safely
# without breaking the dashboard UI's regex parser for the defaults above.
if OPTION_UNDERLYING == "NIFTY":
    LOT_SIZE = 65
    SPREAD_WIDTH = 200
elif OPTION_UNDERLYING == "BANKNIFTY":
    LOT_SIZE = 30
    SPREAD_WIDTH = 500
    STRIKE_INTERVAL = 100
elif OPTION_UNDERLYING == "FINNIFTY":
    LOT_SIZE = 60
elif OPTION_UNDERLYING == "MIDCPNIFTY":
    LOT_SIZE = 120
elif OPTION_UNDERLYING == "NIFTYNXT50":
    LOT_SIZE = 25
elif OPTION_UNDERLYING in ("CRUDEOIL", "GOLDM"):
    LOT_SIZE = 1
    SPREAD_WIDTH = 500
    STRIKE_INTERVAL = 100
    
    SESSION_START_HOUR = 9
    SESSION_START_MINUTE = 30
    TRADE_START_HOUR = 9
    TRADE_START_MINUTE = 30
    
    NO_NEW_ENTRIES_HOUR = 22
    NO_NEW_ENTRIES_MINUTE = 0
    HARD_SQUARE_OFF_HOUR = 22
    HARD_SQUARE_OFF_MINUTE = 45
    
    SESSION_END_HOUR = 23
    SESSION_END_MINUTE = 0
    
    FYERS_OPTION_EXCHANGE = "MCX"
    ZERODHA_OPTION_EXCHANGE = "MCX"
    print(f"  Session:      {SESSION_START_HOUR:02d}:{SESSION_START_MINUTE:02d} - "
          f"{SESSION_END_HOUR:02d}:{SESSION_END_MINUTE:02d} IST")


if __name__ == "__main__":
    validate()
