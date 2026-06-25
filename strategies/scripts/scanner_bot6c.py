#!/usr/bin/env python3
"""
strategies/scripts/scanner.py
==============================
Bot6c Multi-Asset Scanner — Main Entry Point.

Supports two modes:
  --mode backtest   Bar-by-bar simulation on historical DuckDB data
  --mode live       Real-time concurrent scanning via OpenAlgo API

USAGE
-----
  # Run 2-year backtest on all 97 NSE stocks:
  python scanner.py --mode backtest

  # Run backtest on a specific date range:
  python scanner.py --mode backtest --start 2025-01-01 --end 2026-06-01

  # Run backtest on specific symbols only:
  python scanner.py --mode backtest --symbols RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK

  # Export backtest trades to CSV:
  python scanner.py --mode backtest --export trades.csv

  # Run live scanner:
  python scanner.py --mode live

  # Run live scanner with a custom watchlist:
  python scanner.py --mode live --symbols RELIANCE,TCS,INFY

ENVIRONMENT VARIABLES (required for --mode live):
  OPENALGO_API_KEY     OpenAlgo API key
  HOST_SERVER          OpenAlgo host (default: http://127.0.0.1:5000)
  WEBSOCKET_URL        WebSocket URL (default: ws://127.0.0.1:8765)

LOGGING:
  Default: INFO level to stdout + bot6c_scanner.log file
  Add --debug flag for verbose DEBUG output
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup: add openalgo root so `bot6c` can be imported
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent  # strategies/scripts/../../ = openalgo root
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(name)s] %(message)s"
    datefmt = "%H:%M:%S"
    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot6c_scanner.log", mode="a", encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)


log = logging.getLogger("Bot6c.Scanner")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bot6c Multi-Asset Scanner — NSE Equity DTC Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["backtest", "live"],
        required=True,
        help="Execution mode: 'backtest' or 'live'",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Backtest start date (YYYY-MM-DD). Default: 2 years ago.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Backtest end date (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated list of NSE symbols. Default: all 97 from WATCHLIST.",
    )
    parser.add_argument(
        "--db",
        default="db/historify.duckdb",
        help="Path to DuckDB database. Default: db/historify.duckdb",
    )
    parser.add_argument(
        "--export",
        default=None,
        help="Export backtest trade log to this CSV path (e.g. trades.csv).",
    )
    parser.add_argument(
        "--exchange",
        default="NSE",
        help="Exchange for live mode (default: NSE).",
    )
    parser.add_argument(
        "--strategy",
        default="Bot6c_Scanner",
        help="Strategy name for OpenAlgo order tagging (default: Bot6c_Scanner).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose DEBUG logging.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Backtest runner
# ---------------------------------------------------------------------------
def run_backtest_mode(args: argparse.Namespace) -> None:
    from bot6c.backtest_engine import run_backtest
    from bot6c.report import generate_report, export_trades_csv
    from bot6c.config import WATCHLIST, TOTAL_CAPITAL

    symbols = args.symbols.split(",") if args.symbols else WATCHLIST
    symbols = [s.strip().upper() for s in symbols]

    log.info("=" * 60)
    log.info("  BOT6C SCANNER — BACKTEST MODE")
    log.info(f"  Symbols : {len(symbols)}")
    log.info(f"  Start   : {args.start or '2 years ago'}")
    log.info(f"  End     : {args.end or 'today'}")
    log.info(f"  DB      : {args.db}")
    log.info("=" * 60)

    trades = run_backtest(
        db_path=args.db,
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
    )

    generate_report(trades, initial_capital=TOTAL_CAPITAL)

    if args.export:
        export_trades_csv(trades, filepath=args.export)
        log.info(f"Trades exported to: {args.export}")


# ---------------------------------------------------------------------------
# Live runner
# ---------------------------------------------------------------------------
def run_live_mode(args: argparse.Namespace) -> None:
    from bot6c.live_engine import run_live
    from bot6c.config import WATCHLIST

    # Validate environment
    api_key = os.getenv("OPENALGO_API_KEY", "")
    host = os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
    ws_url = (
        os.getenv("WEBSOCKET_URL")
        or f"ws://{os.getenv('WEBSOCKET_HOST', '127.0.0.1')}:{os.getenv('WEBSOCKET_PORT', '8765')}"
    )

    if not api_key:
        log.warning(
            "[LIVE] OPENALGO_API_KEY not set! "
            "Orders will fail unless you are in sandbox mode."
        )

    try:
        from openalgo import api as OpenAlgoAPI
    except ImportError:
        log.error(
            "[LIVE] Cannot import 'openalgo'. "
            "Make sure the package is installed: pip install openalgo"
        )
        sys.exit(1)

    client = OpenAlgoAPI(api_key=api_key, host=host, ws_url=ws_url)

    symbols = args.symbols.split(",") if args.symbols else WATCHLIST
    symbols = [s.strip().upper() for s in symbols]

    log.info("=" * 60)
    log.info("  BOT6C SCANNER — LIVE MODE")
    log.info(f"  Host    : {host}")
    log.info(f"  Symbols : {len(symbols)}")
    log.info(f"  Exchange: {args.exchange}")
    log.info(f"  Strategy: {args.strategy}")
    log.info("=" * 60)

    run_live(
        api_client=client,
        watchlist=symbols,
        exchange=args.exchange,
        strategy_name=args.strategy,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    setup_logging(debug=args.debug)

    if args.mode == "backtest":
        run_backtest_mode(args)
    elif args.mode == "live":
        run_live_mode(args)


if __name__ == "__main__":
    main()
