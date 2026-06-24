"""
bot6/data_layer.py
==================
Abstraction layer for OHLCV data ingestion.

Provides two feed implementations:
  - DuckDBFeed  : Reads from db/historify.duckdb for backtesting
  - LiveFeed    : Fetches from OpenAlgo REST API for live trading

Both expose the same interface so the strategy engine is completely
agnostic to the data source.

Key schema facts (db/historify.duckdb):
  Table: market_data
  Columns: symbol, exchange, interval, timestamp(BIGINT unix-seconds),
           open, high, low, close, volume, oi, created_at
  Filter: exchange='NSE', interval='1m'
"""

from __future__ import annotations

import os
import sys
import math
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

import duckdb
import pandas as pd

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseFeed(ABC):
    """Abstract feed — all implementations must satisfy this interface."""

    @abstractmethod
    def get_bars(self, symbol: str, lookback_bars: int = 200) -> pd.DataFrame:
        """
        Return a DataFrame of recent 1-min OHLCV bars for one symbol.

        Returns
        -------
        pd.DataFrame
            Index   : DatetimeIndex (IST, tz-naive)
            Columns : open, high, low, close, volume
        """

    @abstractmethod
    def get_all_bars_for_backtest(
        self,
        symbols: list[str],
        start_ts: int,
        end_ts: int,
    ) -> dict[str, pd.DataFrame]:
        """
        Bulk load: return a dict {symbol -> DataFrame} for a date range.
        Used by the backtest engine to pre-load everything in one shot.

        Parameters
        ----------
        symbols : list of ticker strings
        start_ts, end_ts : Unix epoch seconds (inclusive)

        Returns
        -------
        dict[str, pd.DataFrame]
            Each DataFrame has DatetimeIndex (IST tz-naive) and
            columns: open, high, low, close, volume
        """


# ---------------------------------------------------------------------------
# DuckDB Feed (Backtest)
# ---------------------------------------------------------------------------

class DuckDBFeed(BaseFeed):
    """
    Reads 1-minute OHLCV data from db/historify.duckdb.

    The database stores timestamps as BIGINT Unix seconds.
    We convert them to tz-naive IST DatetimeIndex using UTC+5:30 offset.
    """

    IST_OFFSET_SECS = 5 * 3600 + 30 * 60  # +05:30 in seconds

    def __init__(self, db_path: str = "db/historify.duckdb"):
        self.db_path = db_path
        if not os.path.exists(db_path):
            raise FileNotFoundError(
                f"DuckDB not found at '{db_path}'. "
                "Run Historify to download data first."
            )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.db_path, read_only=True)

    @staticmethod
    def _ts_to_ist(unix_series: pd.Series) -> pd.DatetimeIndex:
        """Convert BIGINT unix-seconds to IST DatetimeIndex (tz-naive)."""
        return pd.to_datetime(
            unix_series * 1_000_000_000,  # ns
            utc=True
        ).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

    def get_bars(self, symbol: str, lookback_bars: int = 200) -> pd.DataFrame:
        """Return the most recent `lookback_bars` 1-min bars for a symbol."""
        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM market_data
            WHERE symbol = ? AND exchange = 'NSE' AND interval = '1m'
            ORDER BY timestamp DESC
            LIMIT ?
        """
        with self._connect() as con:
            df = con.execute(query, [symbol, lookback_bars]).df()

        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = df.sort_values("timestamp").reset_index(drop=True)
        df.index = self._ts_to_ist(df["timestamp"])
        df.index.name = "datetime"
        return df[["open", "high", "low", "close", "volume"]].copy()

    def get_all_bars_for_backtest(
        self,
        symbols: list[str],
        start_ts: int,
        end_ts: int,
    ) -> dict[str, pd.DataFrame]:
        """
        Bulk-load all NSE bars for the given symbols and unix timestamp range.
        Returns {symbol: DataFrame} sorted chronologically.
        """
        placeholders = ", ".join(["?"] * len(symbols))
        query = f"""
            SELECT symbol, timestamp, open, high, low, close, volume
            FROM market_data
            WHERE symbol IN ({placeholders})
              AND exchange = 'NSE'
              AND interval = '1m'
              AND timestamp >= ?
              AND timestamp <= ?
            ORDER BY timestamp ASC
        """
        params = symbols + [start_ts, end_ts]

        with self._connect() as con:
            df = con.execute(query, params).df()

        if df.empty:
            return {}

        # Convert timestamps once for the whole batch
        df["datetime"] = self._ts_to_ist(df["timestamp"])

        result: dict[str, pd.DataFrame] = {}
        for sym, grp in df.groupby("symbol"):
            sub = grp.sort_values("timestamp").set_index("datetime")
            result[sym] = sub[["open", "high", "low", "close", "volume"]].copy()

        return result

    def get_available_symbols(self, exchange: str = "NSE") -> list[str]:
        """Return all symbols in the data_catalog for a given exchange."""
        query = "SELECT symbol FROM data_catalog WHERE exchange = ? ORDER BY symbol"
        with self._connect() as con:
            rows = con.execute(query, [exchange]).fetchall()
        return [r[0] for r in rows]

    def get_timestamp_range(self, exchange: str = "NSE") -> tuple[int, int]:
        """Return (min_timestamp, max_timestamp) for all NSE data."""
        query = """
            SELECT MIN(first_timestamp), MAX(last_timestamp)
            FROM data_catalog WHERE exchange = ?
        """
        with self._connect() as con:
            row = con.execute(query, [exchange]).fetchone()
        return (row[0] or 0, row[1] or 0)


# ---------------------------------------------------------------------------
# Live Feed (OpenAlgo REST)
# ---------------------------------------------------------------------------

class LiveFeed(BaseFeed):
    """
    Fetches 1-min OHLCV bars from the OpenAlgo REST API in live trading mode.

    Wraps openalgo.api.history() which returns a DataFrame already with
    DatetimeIndex and columns open, high, low, close, volume.
    """

    def __init__(self, api_client, exchange: str = "NSE"):
        self.client = api_client
        self.exchange = exchange

    def get_bars(self, symbol: str, lookback_bars: int = 200) -> pd.DataFrame:
        """
        Fetch recent bars using OpenAlgo client.
        lookback_bars is converted to ~5 calendar days to ensure coverage.
        """
        now = datetime.now()
        # Fetch enough calendar days to cover lookback_bars of 1-min bars
        # ~375 bars per market day → 200 bars needs at most 1 day, but we pad
        days_back = max(5, math.ceil(lookback_bars / 375) + 2)
        start_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")

        try:
            df = self.client.history(
                symbol=symbol,
                exchange=self.exchange,
                interval="1m",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as e:
            # Return empty DataFrame on any network / auth error
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        if df is None or df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # Ensure we have the required columns
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # Return only the most recent lookback_bars rows
        return df[["open", "high", "low", "close", "volume"]].tail(lookback_bars).copy()

    def get_all_bars_for_backtest(
        self,
        symbols: list[str],
        start_ts: int,
        end_ts: int,
    ) -> dict[str, pd.DataFrame]:
        """Not implemented for live feed — use DuckDBFeed for backtest."""
        raise NotImplementedError(
            "LiveFeed does not support bulk historical loading. "
            "Use DuckDBFeed for backtesting."
        )
