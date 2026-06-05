# services/backtest_service.py
"""
OpenAlgo Backtest Service
Performs technical indicator calculations and historical trade simulation.
"""

import math
import numpy as np
import pandas as pd
from datetime import datetime
from database.historify_db import get_ohlcv
from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Calculate Simple Moving Average."""
    return series.rolling(window=period).mean()


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    # Avoid division by zero
    rs = gain / loss.replace(0, np.nan)
    rs = rs.fillna(0)
    
    rsi = 100 - (100 / (1 + rs))
    # Fill initial NaN values
    rsi.iloc[:period] = 50.0
    return rsi


def calculate_macd(series: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate MACD (MACD line, Signal line, Histogram)."""
    fast_ema = calculate_ema(series, fast_period)
    slow_ema = calculate_ema(series, slow_period)
    macd_line = fast_ema - slow_ema
    signal_line = calculate_ema(macd_line, signal_period)
    macd_hist = macd_line - signal_line
    return macd_line, signal_line, macd_hist


def run_backtest(params: dict) -> tuple[bool, dict, int]:
    """
    Run backtest simulation on historical OHLCV data.

    Parameters in dict:
        symbol (str): Symbol name (e.g. SBIN)
        exchange (str): Exchange name (e.g. NSE)
        interval (str): Interval (e.g. 5m, 1h, D)
        start_date (str): ISO date string (YYYY-MM-DD)
        end_date (str): ISO date string (YYYY-MM-DD)
        strategy (str): Strategy key ('sma_crossover', 'ema_crossover', 'rsi', 'macd')
        strategy_params (dict): Parameters specific to the strategy
        capital (float): Initial virtual capital (default: 100000)
        slippage_pct (float): Slippage percentage (default: 0.05)
        commission_flat (float): Flat fee per order (default: 20.0)
        commission_pct (float): Percentage commission per order value (default: 0.03)

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Extract inputs
        symbol = params.get("symbol", "").strip().upper()
        exchange = params.get("exchange", "NSE").strip().upper()
        interval = params.get("interval", "5m").strip()
        start_date_str = params.get("start_date")
        end_date_str = params.get("end_date")
        strategy_name = params.get("strategy", "ema_crossover")
        strat_params = params.get("strategy_params", {})
        
        capital = float(params.get("capital", 100000.0))
        slippage_pct = float(params.get("slippage_pct", 0.05)) / 100.0
        commission_flat = float(params.get("commission_flat", 20.0))
        commission_pct = float(params.get("commission_pct", 0.03)) / 100.0

        if not symbol:
            return False, {"status": "error", "message": "Symbol is required"}, 400

        valid_strategies = ["sma_crossover", "ema_crossover", "rsi", "macd"]
        if strategy_name not in valid_strategies:
            return False, {"status": "error", "message": f"Unsupported strategy '{strategy_name}'"}, 400

        # Convert date strings to timestamps
        start_ts = None
        end_ts = None
        if start_date_str:
            start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp())
        if end_date_str:
            # Add 23:59:59 to include the end date fully
            end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp())

        # Retrieve OHLCV data from DuckDB
        df = get_ohlcv(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts
        )

        if df.empty:
            return False, {"status": "error", "message": f"No historical data found for {symbol} ({exchange}) on interval {interval} in the selected date range."}, 404

        # Sort by timestamp ascending
        df = df.sort_values("timestamp").reset_index(drop=True)
        
        # Convert timestamps back to ISO strings for frontend display
        df["datetime"] = df["timestamp"].apply(lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"))

        # Calculate Indicators & Generate Signals
        close_prices = df["close"]
        df["buy_signal"] = False
        df["sell_signal"] = False

        if strategy_name == "sma_crossover":
            fast_p = int(strat_params.get("fast_period", 9))
            slow_p = int(strat_params.get("slow_period", 21))
            df["fast_indicator"] = calculate_sma(close_prices, fast_p)
            df["slow_indicator"] = calculate_sma(close_prices, slow_p)
            
            # Generate crossover signals
            for i in range(1, len(df)):
                # Skip if indicators aren't calculated yet
                if pd.isna(df.loc[i, "fast_indicator"]) or pd.isna(df.loc[i, "slow_indicator"]):
                    continue
                
                prev_fast = df.loc[i-1, "fast_indicator"]
                prev_slow = df.loc[i-1, "slow_indicator"]
                curr_fast = df.loc[i, "fast_indicator"]
                curr_slow = df.loc[i, "slow_indicator"]
                
                if prev_fast <= prev_slow and curr_fast > curr_slow:
                    df.loc[i, "buy_signal"] = True
                elif prev_fast >= prev_slow and curr_fast < curr_slow:
                    df.loc[i, "sell_signal"] = True

        elif strategy_name == "ema_crossover":
            fast_p = int(strat_params.get("fast_period", 9))
            slow_p = int(strat_params.get("slow_period", 21))
            df["fast_indicator"] = calculate_ema(close_prices, fast_p)
            df["slow_indicator"] = calculate_ema(close_prices, slow_p)
            
            # Generate crossover signals
            for i in range(1, len(df)):
                if pd.isna(df.loc[i, "fast_indicator"]) or pd.isna(df.loc[i, "slow_indicator"]):
                    continue
                
                prev_fast = df.loc[i-1, "fast_indicator"]
                prev_slow = df.loc[i-1, "slow_indicator"]
                curr_fast = df.loc[i, "fast_indicator"]
                curr_slow = df.loc[i, "slow_indicator"]
                
                if prev_fast <= prev_slow and curr_fast > curr_slow:
                    df.loc[i, "buy_signal"] = True
                elif prev_fast >= prev_slow and curr_fast < curr_slow:
                    df.loc[i, "sell_signal"] = True

        elif strategy_name == "rsi":
            period = int(strat_params.get("period", 14))
            oversold = float(strat_params.get("oversold", 30.0))
            overbought = float(strat_params.get("overbought", 70.0))
            
            df["rsi"] = calculate_rsi(close_prices, period)
            
            # Generate signals: buy when crossing below oversold, sell when crossing above overbought
            for i in range(1, len(df)):
                if pd.isna(df.loc[i-1, "rsi"]) or pd.isna(df.loc[i, "rsi"]):
                    continue
                
                prev_rsi = df.loc[i-1, "rsi"]
                curr_rsi = df.loc[i, "rsi"]
                
                # Cross below oversold (long entry trigger)
                if prev_rsi >= oversold and curr_rsi < oversold:
                    df.loc[i, "buy_signal"] = True
                # Cross above overbought (long exit trigger)
                elif prev_rsi <= overbought and curr_rsi > overbought:
                    df.loc[i, "sell_signal"] = True

        elif strategy_name == "macd":
            fast_p = int(strat_params.get("fast_period", 12))
            slow_p = int(strat_params.get("slow_period", 26))
            signal_p = int(strat_params.get("signal_period", 9))
            
            macd_line, signal_line, macd_hist = calculate_macd(close_prices, fast_p, slow_p, signal_p)
            df["macd_line"] = macd_line
            df["signal_line"] = signal_line
            df["macd_hist"] = macd_hist
            
            # Generate signals on MACD line crossing Signal line
            for i in range(1, len(df)):
                if pd.isna(df.loc[i-1, "macd_line"]) or pd.isna(df.loc[i, "macd_line"]):
                    continue
                
                prev_macd = df.loc[i-1, "macd_line"]
                prev_sig = df.loc[i-1, "signal_line"]
                curr_macd = df.loc[i, "macd_line"]
                curr_sig = df.loc[i, "signal_line"]
                
                if prev_macd <= prev_sig and curr_macd > curr_sig:
                    df.loc[i, "buy_signal"] = True
                elif prev_macd >= prev_sig and curr_macd < curr_sig:
                    df.loc[i, "sell_signal"] = True
        else:
            return False, {"status": "error", "message": f"Unsupported strategy '{strategy_name}'"}, 400

        # Backtest Trade Simulation (Long-Only Event-Driven Simulator)
        current_capital = capital
        peak_capital = capital
        max_drawdown = 0.0
        
        trades = []
        open_position = None  # Dict tracking active trade: entry_price, qty, datetime, timestamp
        
        capital_history = [capital] * len(df)

        for i in range(len(df)):
            row = df.loc[i]
            price = row["close"]
            dt_str = row["datetime"]
            ts = row["timestamp"]

            # If we have an open position, check for exit signal
            if open_position is not None:
                if row["sell_signal"] or i == len(df) - 1:
                    # Close position
                    qty = open_position["qty"]
                    entry_price = open_position["entry_price"]
                    entry_dt = open_position["datetime"]
                    
                    # Apply slippage on exit (sells at slightly lower price)
                    exit_price = price * (1.0 - slippage_pct)
                    exit_value = exit_price * qty
                    
                    # Calculate exit commissions
                    exit_fee = commission_flat + (exit_value * commission_pct)
                    
                    # Return proceeds to capital
                    net_return = exit_value - exit_fee
                    current_capital += net_return
                    
                    # Calculate trade metrics
                    gross_pnl = (exit_price - entry_price) * qty
                    net_pnl = gross_pnl - open_position["entry_fee"] - exit_fee
                    pnl_pct = (net_pnl / (entry_price * qty)) * 100.0 if qty > 0 else 0.0
                    
                    trades.append({
                        "id": len(trades) + 1,
                        "direction": "BUY",  # We went long
                        "qty": qty,
                        "entry_time": entry_dt,
                        "entry_price": round(entry_price, 2),
                        "entry_fee": round(open_position["entry_fee"], 2),
                        "exit_time": dt_str,
                        "exit_price": round(exit_price, 2),
                        "exit_fee": round(exit_fee, 2),
                        "gross_pnl": round(gross_pnl, 2),
                        "net_pnl": round(net_pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "exit_reason": "Strategy Signal" if row["sell_signal"] else "End of Data"
                    })
                    
                    open_position = None
            
            # If no open position, check for entry signal
            elif row["buy_signal"] and i < len(df) - 1:
                # Calculate quantity to buy using 95% of current capital (to leave headroom for commissions/slippage)
                available_capital = current_capital * 0.95
                
                # Apply slippage on entry (buys at slightly higher price)
                entry_price = price * (1.0 + slippage_pct)
                
                if available_capital > entry_price:
                    qty = math.floor(available_capital / entry_price)
                    if qty > 0:
                        entry_value = entry_price * qty
                        
                        # Calculate entry commissions
                        entry_fee = commission_flat + (entry_value * commission_pct)
                        
                        # Deduct entry value and fee from capital
                        current_capital -= (entry_value + entry_fee)
                        
                        open_position = {
                            "entry_price": entry_price,
                            "qty": qty,
                            "datetime": dt_str,
                            "timestamp": ts,
                            "entry_fee": entry_fee
                        }

            # Track capital curve & drawdown
            effective_capital = current_capital
            if open_position is not None:
                # Add current valuation of open position
                effective_capital += (price * open_position["qty"])
            
            capital_history[i] = effective_capital
            
            if effective_capital > peak_capital:
                peak_capital = effective_capital
            
            dd = ((peak_capital - effective_capital) / peak_capital) * 100.0 if peak_capital > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        # Add capital history to dataframe
        df["capital_curve"] = capital_history

        # Calculate final metrics
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t["net_pnl"] > 0)
        losing_trades = sum(1 for t in trades if t["net_pnl"] <= 0)
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
        
        gross_profits = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        gross_losses = sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
        
        profit_factor = (gross_profits / abs(gross_losses)) if gross_losses != 0 else (gross_profits if gross_profits > 0 else 1.0)
        net_pnl = sum(t["net_pnl"] for t in trades)
        roi = (net_pnl / capital) * 100.0
        avg_trade_pnl = (net_pnl / total_trades) if total_trades > 0 else 0.0

        # Extract chart data for plotly (downsampled if too large to prevent frontend lag)
        chart_df = df.copy()
        if len(chart_df) > 2000:
            # Keep indicators and markers intact but downsample candlestick density
            step = len(chart_df) // 1000
            chart_df = chart_df.iloc[::step].reset_index(drop=True)

        chart_data = []
        for _, r in chart_df.iterrows():
            item = {
                "timestamp": int(r["timestamp"]),
                "datetime": r["datetime"],
                "open": round(r["open"], 2),
                "high": round(r["high"], 2),
                "low": round(r["low"], 2),
                "close": round(r["close"], 2),
                "volume": int(r["volume"]),
                "capital": round(r["capital_curve"], 2)
            }
            if "fast_indicator" in r and not pd.isna(r["fast_indicator"]):
                item["fast_indicator"] = round(r["fast_indicator"], 2)
            if "slow_indicator" in r and not pd.isna(r["slow_indicator"]):
                item["slow_indicator"] = round(r["slow_indicator"], 2)
            if "rsi" in r and not pd.isna(r["rsi"]):
                item["rsi"] = round(r["rsi"], 2)
            if "macd_line" in r and not pd.isna(r["macd_line"]):
                item["macd_line"] = round(r["macd_line"], 2)
                item["signal_line"] = round(r["signal_line"], 2)
                item["macd_hist"] = round(r["macd_hist"], 2)
            
            # Check if there is an entry/exit marker at this bar
            item["buy_marker"] = bool(r["buy_signal"])
            item["sell_marker"] = bool(r["sell_signal"])
            
            chart_data.append(item)

        metrics = {
            "initial_capital": round(capital, 2),
            "final_capital": round(capital + net_pnl, 2),
            "net_pnl": round(net_pnl, 2),
            "roi_pct": round(roi, 2),
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "avg_trade_pnl": round(avg_trade_pnl, 2)
        }

        response = {
            "status": "success",
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "strategy": strategy_name,
            "metrics": metrics,
            "trades": trades,
            "chart_data": chart_data
        }
        
        return True, response, 200

    except Exception as e:
        logger.exception(f"Error in backtest execution: {e}")
        return False, {"status": "error", "message": f"Backtest failed: {str(e)}"}, 500
