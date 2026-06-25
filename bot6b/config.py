"""
bot6b/config.py
==============
All configurable parameters for Bot6b DTC Intraday Strategy.
Edit this file to tune the strategy without touching core logic.
"""

# --------------------------------------------------------------------------- #
# INDICATOR PARAMETERS (DTC & HULL BBI)
# --------------------------------------------------------------------------- #
EMA_LENGTHS: list[int] = [8, 13, 21, 26, 34, 40]
HULL_PERIOD: int = 21

# --------------------------------------------------------------------------- #
# CAPITAL & LEVERAGE
# --------------------------------------------------------------------------- #
CAPITAL_PER_TRADE: float = 50_000.0   # Rs allocated capital per trade
LEVERAGE: int = 5                      # Broker intraday leverage (5x)
MAX_EXPOSURE: float = CAPITAL_PER_TRADE * LEVERAGE

# --------------------------------------------------------------------------- #
# SCANNER / MULTI-ASSET CONFIG
# --------------------------------------------------------------------------- #
CAPITAL_PER_TRADE_SCANNER: float = 50_000.0  # Rs per position in scanner mode
MAX_SIMULTANEOUS_POSITIONS: int = 10         # Max concurrent open positions
TOTAL_CAPITAL: float = 500_000.0             # Total deployed capital

WATCHLIST: list[str] = [
    "ABB", "ADANIENSOL", "ADANIENT", "ADANIGREEN", "ADANIPORTS",
    "ADANIPOWER", "AMBUJACEM", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BANKBARODA", "BEL",
    "BHARATFORG", "BHARTIARTL", "BOSCHLTD", "BPCL", "BRITANNIA",
    "CANBK", "CGPOWER", "CHOLAFIN", "CIPLA", "COALINDIA",
    "CUMMINSIND", "DABUR", "DIVISLAB", "DLF", "DMART",
    "DRREDDY", "EICHERMOT", "ETERNAL", "GODREJCP", "GRASIM",
    "HAL", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE",
    "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "HYUNDAI", "ICICIBANK",
    "ICICIGI", "ICICIPRULI", "INDHOTEL", "INDIGO", "INDUSINDBK",
    "INFY", "IOC", "ITC", "JIOFIN", "JSWSTEEL",
    "KOTAKBANK", "LICI", "LT", "M&M", "MANKIND",
    "MARICO", "MARUTI", "MAXHEALTH", "NAUKRI", "NESTLEIND",
    "NTPC", "ONGC", "PAGEIND", "PERSISTENT", "PFC",
    "PIDILITIND", "PNB", "POWERGRID", "RECLTD", "RELIANCE",
    "SBICARD", "SBILIFE", "SBIN", "SHRIRAMFIN", "SIEMENS",
    "SUNPHARMA", "TATACONSUM", "TATAPOWER", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TORNTPHARM", "TRENT", "TVSMOTOR",
    "ULTRACEMCO", "VBL", "VEDL", "WIPRO", "ZYDUSLIFE",
]

# --------------------------------------------------------------------------- #
# RISK MANAGEMENT & EXITS
# --------------------------------------------------------------------------- #
TARGET_PCT: float = 0.005           # 0.5% hard target
SPREAD_SL_PCT: float = 0.15         # 15% risk stop
HMA_EXIT_BUFFER: float = 5.0        # Exit buffer (Rs) when Hull flips against us

# --------------------------------------------------------------------------- #
# TIME FENCES (all times in 24-hr HH:MM format, IST)
# --------------------------------------------------------------------------- #
MARKET_START: str = "09:15"      # No entries before this time (single-bot legacy)
SCANNER_START: str = "09:30"     # Scanner: no entries before this time
CUTOFF_TIME: str = "14:45"       # No NEW entries after this time
SQUARE_OFF_TIME: str = "15:15"   # Hard square-off — market order all open positions

# --------------------------------------------------------------------------- #
# LOGGING
# --------------------------------------------------------------------------- #
LOG_FILE: str = "bot6b_trades.log"
TRADE_CSV: str = "bot6b_tradelog.csv"

# --------------------------------------------------------------------------- #
# CONTEXTUAL FILTERS (VWAP & RVOL)
# --------------------------------------------------------------------------- #
USE_VWAP_FILTER: bool = False
USE_RVOL_FILTER: bool = False
RVOL_THRESHOLD: float = 2.0       # Signal bar must have 2x average volume
RVOL_LENGTH: int = 20             # Moving average period for volume baseline
