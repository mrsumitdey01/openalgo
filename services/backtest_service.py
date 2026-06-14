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

def calculate_statutory_charges(profile, value, qty, side, legs=1, apply_brokerage=True, is_spread=False):
    # For directional spreads (not straddles), the passed value is often just the net spread premium.
    # We approximate gross premium turnover as 5x the net spread premium for realistic STT/Txn fees.
    if is_spread:
        value = value * 5.0
    """
    Calculates exact statutory charges for Indian markets based on the selected profile.
    """
    brokerage = 0.0
    stt = 0.0
    txn = 0.0
    gst = 0.0
    sebi = 0.0
    stamp = 0.0

    if profile == "fo_options":
        brokerage = 20.0 * legs if apply_brokerage else 0.0
        # Oct 1, 2024 revision: Options STT increased to 0.1% on premium (sell side)
        stt = (value * 0.001) if side == "SELL" else 0.0
        # Oct 1, 2024 revision: True-to-label NSE transaction fee is 0.03503%
        txn = value * 0.0003503
        sebi = value * 0.000001
        stamp = (value * 0.00003) if side == "BUY" else 0.0
        gst = (brokerage + sebi + txn) * 0.18
    elif profile == "fo_futures":
        brokerage = 20.0 * legs if apply_brokerage else 0.0
        # Oct 1, 2024 revision: Futures STT increased to 0.02% (sell side)
        stt = (value * 0.0002) if side == "SELL" else 0.0
        # Oct 1, 2024 revision: True-to-label NSE transaction fee is 0.00173%
        txn = value * 0.0000173
        sebi = value * 0.000001
        stamp = (value * 0.00002) if side == "BUY" else 0.0
        gst = (brokerage + sebi + txn) * 0.18
    elif profile == "equity_intraday":
        brokerage = min(20.0, value * 0.0003)
        stt = (value * 0.00025) if side == "SELL" else 0.0
        txn = value * 0.0000325
        sebi = value * 0.000001
        stamp = (value * 0.00003) if side == "BUY" else 0.0
        gst = (brokerage + sebi + txn) * 0.18
    elif profile == "equity_delivery":
        brokerage = 0.0
        stt = value * 0.001
        txn = value * 0.0000325
        sebi = value * 0.000001
        stamp = (value * 0.00015) if side == "BUY" else 0.0
        gst = (brokerage + sebi + txn) * 0.18

    total_fee = brokerage + stt + txn + gst + sebi + stamp
    return total_fee, {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "txn": round(txn, 2),
        "gst": round(gst, 2),
        "sebi": round(sebi, 2),
        "stamp": round(stamp, 2),
        "total": round(total_fee, 2)
    }

def run_bot1_backtest(params: dict) -> tuple[bool, dict, int]:
    try:
        from strategies.scripts.bot1_hull_dtc_ribbon import HullBBI, DTCRibbon, check_signals
        from datetime import time as time_obj

        symbol = params.get("symbol", "BANKNIFTY").strip().upper()
        exchange = params.get("exchange", "NSE").strip().upper()
        interval = "1m"
        start_date_str = params.get("start_date")
        end_date_str = params.get("end_date")
        
        capital = float(params.get("capital", 100000.0))
        execution_mode = params.get("execution_mode", "options_spread")
        
        if execution_mode == "futures":
            charges_profile = "fo_futures"
        else:
            charges_profile = "fo_options"
            
        lot_size = int(params.get("lot_size", 30))  # Fixed qty per trade

        start_ts = None
        end_ts = None
        if start_date_str:
            start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp())
        if end_date_str:
            end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp())

        df = get_ohlcv(
            symbol=symbol,
            exchange="NSE_INDEX" if exchange == "NSE" else exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts
        )

        if df.empty:
            return False, {"status": "error", "message": f"No historical data found for {symbol} ({exchange})"}, 404

        df = df.sort_values("timestamp").reset_index(drop=True)
        df["datetime"] = df["timestamp"].apply(lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"))

        hull = HullBBI(length=21)
        df = hull.compute(df)
        
        dtc = DTCRibbon()
        df = dtc.compute(df)

        # â”€â”€ Trading session constants (matching live bot) â”€â”€
        ENTRY_START = time_obj(9, 30)
        NO_NEW_ENTRIES = time_obj(14, 45)
        HARD_SQUARE_OFF = time_obj(15, 15)

        # Spread delta converts spot movement to profile-specific PnL
        if execution_mode == "futures":
            spread_delta = 1.0
        elif execution_mode in ["options_buying", "options_selling"]:
            spread_delta = 0.5
        else:
            spread_delta = 0.25

        current_capital = capital
        peak_capital = capital
        max_drawdown = 0.0
        
        trades = []
        open_position = None
        capital_history = [capital] * len(df)


        for i in range(2, len(df)):
            row = df.loc[i]
            price = row["close"]
            dt_str = row["datetime"]
            candle_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            candle_time = candle_dt.time()
            
            # â”€â”€ Build signal slice â”€â”€
            # Include candle i so that get_last_completed_candle (which returns
            # iloc[-2] for non-DatetimeIndex) evaluates candle i-1 â€” the true
            # last completed candle. Trade execution uses candle i's close price.
            slice_end = i + 1
            slice_start = max(0, slice_end - 6)
            slice_df = df.iloc[slice_start:slice_end]
            signal = check_signals(slice_df, open_position["type"] if open_position else None)

            # â”€â”€ 1. EOD Hard Square-Off (matching live bot's 15:15 rule) â”€â”€
            if open_position is not None and candle_time >= HARD_SQUARE_OFF:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    gross_pnl = spot_diff * spread_delta * open_position["qty"]
                    current_spread_val = open_position["entry_spread"] + (spot_diff * spread_delta)
                else:
                    gross_pnl = -spot_diff * spread_delta * open_position["qty"]
                    current_spread_val = open_position["entry_spread"] + (spot_diff * spread_delta)
                
                exit_value = abs(current_spread_val * open_position["qty"])
                exit_side = "BUY" if open_position["type"] == "SHORT" else "SELL"
                exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, open_position["qty"], exit_side)
                
                net_pnl = gross_pnl - open_position["entry_fee"] - exit_fee
                current_capital += (open_position["margin_blocked"] + gross_pnl - exit_fee)
                
                pnl_pct = (net_pnl / (open_position["entry_spread"] * open_position["qty"])) * 100.0 if (open_position["entry_spread"] > 0 and open_position["qty"] > 0) else 0.0
                
                trades.append({
                    "id": len(trades) + 1,
                    "direction": open_position["type"],
                    "qty": open_position["qty"],
                    "entry_time": open_position["datetime"],
                    "entry_price": round(open_position["entry_spread"], 2),
                    "entry_fee": round(open_position["entry_fee"], 2),
                    "exit_time": dt_str,
                    "exit_price": round(current_spread_val, 2),
                    "exit_fee": round(exit_fee, 2),
                    "gross_pnl": round(gross_pnl, 2),
                    "net_pnl": round(net_pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "exit_reason": "EOD Square-Off",
                    "fee_breakdown": fee_breakdown
                })
                open_position = None

            # â”€â”€ 2. Position Exit Logic â”€â”€
            elif open_position is not None:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    current_spread_val = open_position["entry_spread"] + (spot_diff * spread_delta)
                    temp_gross_pnl = spot_diff * spread_delta * open_position["qty"]
                else:
                    current_spread_val = open_position["entry_spread"] + (spot_diff * spread_delta)
                    temp_gross_pnl = -spot_diff * spread_delta * open_position["qty"]
                
                # Evaluate PnL Stop
                pnl_stop_breached = False
                if execution_mode == "futures":
                    if open_position["type"] == "LONG" and spot_diff <= -150.0:
                        pnl_stop_breached = True
                    elif open_position["type"] == "SHORT" and spot_diff >= 150.0:
                        pnl_stop_breached = True
                else:
                    entry_value = open_position["entry_spread"] * open_position["qty"]
                    if entry_value > 0 and temp_gross_pnl <= -0.15 * entry_value:
                        pnl_stop_breached = True
                    
                # Evaluate Structural Stop
                structural_stop_breached = False
                struct_stop = open_position.get("structural_stop")
                if struct_stop:
                    if open_position["type"] == "LONG" and price < struct_stop:
                        structural_stop_breached = True
                    elif open_position["type"] == "SHORT" and price > struct_stop:
                        structural_stop_breached = True
                
                # Determine exit with correct priority: stops > signal > end-of-data
                should_exit = False
                exit_reason = ""
                if pnl_stop_breached:
                    should_exit = True
                    exit_reason = "15% PnL Stop"
                elif structural_stop_breached:
                    should_exit = True
                    exit_reason = "Structural Stop"
                elif signal in ["EXIT_LONG", "EXIT_SHORT"]:
                    should_exit = True
                    exit_reason = "Bot Exit Signal"
                elif i == len(df) - 1:
                    should_exit = True
                    exit_reason = "End of Data"
                
                if should_exit:
                    qty = open_position["qty"]
                    exit_value = abs(current_spread_val * qty)
                    exit_side = "BUY" if open_position["type"] == "SHORT" else "SELL"
                    exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, qty, exit_side, legs=2 if 'spread' in execution_mode else 1, is_spread=('spread' in execution_mode))

                    gross_pnl = temp_gross_pnl
                    net_pnl = gross_pnl - open_position["entry_fee"] - exit_fee
                    current_capital += (open_position["margin_blocked"] + gross_pnl - exit_fee)
                    
                    pnl_pct = (net_pnl / (open_position["entry_spread"] * qty)) * 100.0 if (open_position["entry_spread"] > 0 and qty > 0) else 0.0
                    
                    trades.append({
                        "id": len(trades) + 1,
                        "direction": open_position["type"],
                        "qty": qty,
                        "entry_time": open_position["datetime"],
                        "entry_price": round(open_position["entry_spread"], 2),
                        "entry_fee": round(open_position["entry_fee"], 2),
                        "exit_time": dt_str,
                        "exit_price": round(current_spread_val, 2),
                        "exit_fee": round(exit_fee, 2),
                        "gross_pnl": round(gross_pnl, 2),
                        "net_pnl": round(net_pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "exit_reason": exit_reason,
                        "fee_breakdown": fee_breakdown
                    })
                    open_position = None


            # â”€â”€ 3. Position Entry Logic â”€â”€
            elif signal in ["LONG", "SHORT"] and i < len(df) - 1:
                # Enforce trading hours (matching live bot time windows)
                in_entry_window = (ENTRY_START <= candle_time <= NO_NEW_ENTRIES)
                
                if in_entry_window:
                    # Dynamic margin based on spot price (works for any underlying)
                    if execution_mode == "futures":
                        margin_per_qty = price * 0.10
                        entry_spread = price
                    elif execution_mode == "options_buying":
                        margin_per_qty = price * 0.01
                        entry_spread = price * 0.01
                    elif execution_mode == "options_selling":
                        margin_per_qty = price * 0.10
                        entry_spread = price * 0.01
                    else:  # options_spread
                        margin_per_qty = price * 0.005
                        entry_spread = price * 0.005
                    
                    qty = lot_size  # Fixed quantity: the user's chosen lot size
                    margin_required = margin_per_qty * qty
                    entry_value = entry_spread * qty
                    
                    entry_side = "SELL" if signal == "SHORT" else "BUY"
                    entry_fee, fee_breakdown = calculate_statutory_charges(charges_profile, entry_value, qty, entry_side, legs=2 if 'spread' in execution_mode else 1)
                    
                    # Margin + fee check: skip trade if capital is insufficient
                    if current_capital >= (margin_required + entry_fee):
                        current_capital -= (margin_required + entry_fee)
                        
                        # Compute structural stop from last 5 candles
                        lookback = 5
                        if i >= lookback:
                            candles = df.iloc[i-lookback : i]
                            if signal == "LONG":
                                structural_stop = float(candles["low"].min())
                            else:
                                structural_stop = float(candles["high"].max())
                        else:
                            structural_stop = price - 100 if signal == "LONG" else price + 100
                            
                        open_position = {
                            "type": signal,
                            "entry_spot": price,
                            "entry_spread": entry_spread,
                            "qty": qty,
                            "datetime": dt_str,
                            "entry_fee": entry_fee,
                            "structural_stop": structural_stop,
                            "margin_blocked": margin_required
                        }

            # â”€â”€ Capital curve and drawdown tracking â”€â”€
            effective_capital = current_capital
            if open_position is not None:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    unrealized_pnl = spot_diff * spread_delta * open_position["qty"]
                else:
                    unrealized_pnl = -spot_diff * spread_delta * open_position["qty"]
                effective_capital += open_position["margin_blocked"] + unrealized_pnl
            
            capital_history[i] = effective_capital
            if effective_capital > peak_capital:
                peak_capital = effective_capital
            
            dd = ((peak_capital - effective_capital) / peak_capital) * 100.0 if peak_capital > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        df["capital_curve"] = capital_history

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

        chart_df = df.copy()
        if len(chart_df) > 2000:
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
            "strategy": "bot1_hull_dtc_ribbon",
            "metrics": metrics,
            "trades": trades,
            "chart_data": chart_data
        }
        
        return True, response, 200

    except Exception as e:
        logger.exception(f"Error in Bot 1 backtest execution: {e}")
        return False, {"status": "error", "message": f"Backtest failed: {str(e)}"}, 500


def run_bot2_backtest(params: dict) -> tuple[bool, dict, int]:
    try:
        from strategies.scripts.bot2_ema_momentum import EMAMomentum, check_signals
        from datetime import time as time_obj
        from database.historify_db import get_ohlcv
        import logging
        from datetime import datetime
        logger = logging.getLogger(__name__)

        symbol = params.get("symbol", "BANKNIFTY").strip().upper()
        exchange = params.get("exchange", "NSE").strip().upper()
        interval = "1m"
        start_date_str = params.get("start_date")
        end_date_str = params.get("end_date")
        capital = float(params.get("capital", 100000.0))
        execution_mode = params.get("execution_mode", "options_spread")

        charges_profile = "fo_futures" if execution_mode == "futures" else "fo_options"
        
        # The frontend Qty box sends the raw total units to trade inside "lot_size" parameter
        total_qty_units = int(params.get("lot_size", 1))

        start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp()) if start_date_str else None
        end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp()) if end_date_str else None

        df = get_ohlcv(
            symbol=symbol,
            exchange="NSE_INDEX" if exchange == "NSE" else exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts
        )

        if df.empty:
            return False, {"status": "error", "message": "No historical data found"}, 404

        df = df.sort_values("timestamp").reset_index(drop=True)
        df["datetime"] = df["timestamp"].apply(lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"))

        # Holy Grail NSE Parameters
        ema_momentum = EMAMomentum(fast_period=21, slow_period=100)
        df = ema_momentum.compute(df)

        ENTRY_START = time_obj(9, 30)
        NO_NEW_ENTRIES = time_obj(15, 0)
        HARD_SQUARE_OFF = time_obj(15, 15)

        spread_delta = 1.0 if execution_mode == "futures" else (0.5 if "buying" in execution_mode or "selling" in execution_mode else 0.25)

        current_capital = capital
        peak_capital = capital
        max_drawdown = 0.0
        
        trades = []
        open_position = None
        capital_history = [capital] * len(df)
        
        for i in range(2, len(df)):
            row = df.loc[i]
            price = row["close"]
            dt_str = row["datetime"]
            candle_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").time()
            
            slice_df = df.iloc[max(0, i-5):i+1]
            signal = check_signals(slice_df, open_position["type"] if open_position else None)

            if open_position is not None and candle_time >= HARD_SQUARE_OFF:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    gross_pnl = spot_diff * spread_delta * total_qty_units
                else:
                    gross_pnl = -spot_diff * spread_delta * total_qty_units
                
                exit_value = abs(open_position["entry_spread"] + (spot_diff * spread_delta)) * total_qty_units
                exit_side = "BUY" if open_position["type"] == "SHORT" else "SELL"
                exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side, legs=2 if 'spread' in execution_mode else 1)

                net_pnl = gross_pnl - open_position["entry_fee"] - exit_fee
                current_capital += (open_position["margin_blocked"] + gross_pnl - exit_fee)
                
                trades.append({
                    "id": len(trades) + 1,
                    "direction": open_position["type"],
                    "qty": total_qty_units,
                    "entry_time": open_position["datetime"],
                    "entry_price": open_position["entry_spread"],
                    "exit_time": dt_str,
                    "exit_price": open_position["entry_spread"] + (spot_diff * spread_delta),
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "pnl_pct": (net_pnl / (open_position["entry_spread"] * total_qty_units)) * 100 if open_position["entry_spread"] > 0 else 0,
                    "exit_reason": "EOD Square-Off",
                })
                open_position = None

            elif open_position is not None:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    temp_gross_pnl = spot_diff * spread_delta * total_qty_units
                    current_spread_val = open_position["entry_spread"] + (spot_diff * spread_delta)
                    excursion = spot_diff
                else:
                    temp_gross_pnl = -spot_diff * spread_delta * total_qty_units
                    current_spread_val = open_position["entry_spread"] + (spot_diff * spread_delta)
                    excursion = -spot_diff
                    
                if excursion > open_position["mfe"]:
                    open_position["mfe"] = excursion
                    
                mfe = open_position["mfe"]
                should_exit = False
                exit_reason = ""
                
                # Holy Grail Stops for NSE
                tp_pts = 300
                trail_pts = 150
                
                if mfe >= trail_pts and excursion <= mfe - (trail_pts * 0.5):
                    should_exit = True
                    exit_reason = "Trailing Stop"
                elif excursion <= -trail_pts:
                    should_exit = True
                    exit_reason = "Hard Stop"
                elif excursion >= tp_pts:
                    should_exit = True
                    exit_reason = "Take Profit"
                elif i == len(df) - 1:
                    should_exit = True
                    exit_reason = "End of Data"

                if should_exit:
                    exit_value = abs(current_spread_val * total_qty_units)
                    exit_side = "BUY" if open_position["type"] == "SHORT" else "SELL"
                    exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side, legs=2 if 'spread' in execution_mode else 1, is_spread=('spread' in execution_mode))

                    net_pnl = temp_gross_pnl - open_position["entry_fee"] - exit_fee
                    current_capital += (open_position["margin_blocked"] + temp_gross_pnl - exit_fee)

                    trades.append({
                        "id": len(trades) + 1,
                        "direction": open_position["type"],
                        "qty": total_qty_units,
                        "entry_time": open_position["datetime"],
                        "entry_price": open_position["entry_spread"],
                        "exit_time": dt_str,
                        "exit_price": current_spread_val,
                        "gross_pnl": temp_gross_pnl,
                        "net_pnl": net_pnl,
                        "pnl_pct": (net_pnl / (open_position["entry_spread"] * total_qty_units)) * 100 if open_position["entry_spread"] > 0 else 0,
                        "exit_reason": exit_reason,
                    })
                    open_position = None

            elif signal in ["LONG", "SHORT"] and i < len(df) - 1:
                in_entry_window = (ENTRY_START <= candle_time <= NO_NEW_ENTRIES)
                if in_entry_window:
                    entry_spread = price * (0.005 if execution_mode == "options_spread" else 1.0)
                    margin_per_unit = price * (0.005 if execution_mode == "options_spread" else 0.10)
                    
                    margin_required = margin_per_unit * total_qty_units
                    entry_value = entry_spread * total_qty_units

                    entry_side = "SELL" if signal == "SHORT" else "BUY"
                    entry_fee, fee_breakdown = calculate_statutory_charges(charges_profile, entry_value, total_qty_units, entry_side, legs=2 if 'spread' in execution_mode else 1)

                    if current_capital >= (margin_required + entry_fee):
                        current_capital -= (margin_required + entry_fee)
                        open_position = {
                            "type": signal,
                            "entry_spot": price,
                            "entry_spread": entry_spread,
                            "datetime": dt_str,
                            "entry_fee": entry_fee,
                            "margin_blocked": margin_required,
                            "mfe": 0.0
                        }

            effective_capital = current_capital
            if open_position is not None:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    unrealized_pnl = spot_diff * spread_delta * total_qty_units
                else:
                    unrealized_pnl = -spot_diff * spread_delta * total_qty_units
                effective_capital += open_position["margin_blocked"] + unrealized_pnl
            
            capital_history[i] = effective_capital
            if effective_capital > peak_capital:
                peak_capital = effective_capital
            
            dd = ((peak_capital - effective_capital) / peak_capital) * 100.0 if peak_capital > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        df["capital_curve"] = capital_history
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

        chart_df = df.copy()
        if len(chart_df) > 2000:
            step = len(chart_df) // 1000
            chart_df = chart_df.iloc[::step].reset_index(drop=True)
        chart_data = [{"timestamp": int(r["timestamp"]), "datetime": r["datetime"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"], "capital": r["capital_curve"]} for _, r in chart_df.iterrows()]

        response = {
            "status": "success",
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "strategy": "bot2_ema_momentum",
            "metrics": metrics,
            "trades": trades,
            "chart_data": chart_data
        }
        return True, response, 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, {"status": "error", "message": str(e)}, 500



def run_bot3_backtest(params: dict) -> tuple[bool, dict, int]:
    try:
        import pandas as pd
        import numpy as np
        from datetime import datetime, time as time_obj
        from database.historify_db import get_ohlcv
        from strategies.scripts.bot1_hull_dtc_ribbon import DTCRibbon
        from strategies.scripts.bot3_dtc_sar import check_bot3_signals
        
        symbol = params.get("symbol", "BANKNIFTY")
        exchange = params.get("exchange", "NSE")
        interval = "1m"
        start_date_str = params.get("start_date")
        end_date_str = params.get("end_date")
        capital = float(params.get("capital", 100000.0))
        execution_mode = params.get("execution_mode", "options_spread")
        apply_brokerage = params.get("apply_brokerage", True)

        charges_profile = "fo_futures" if execution_mode == "futures" else "fo_options"
        total_qty_units = int(params.get("lot_size", 1))

        start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp()) if start_date_str else None
        end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp()) if end_date_str else None

        df = get_ohlcv(
            symbol,
            exchange="NSE_INDEX" if exchange == "NSE" else exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts
        )
        if df.empty:
            return False, {"status": "error", "message": "No historical data found"}, 404

        df = df.sort_values("timestamp").reset_index(drop=True)
        df["datetime"] = df["timestamp"].apply(lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"))

        dtc = DTCRibbon()
        df = dtc.compute(df)
        
        # Calculate ATR for dynamic trailing
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = true_range.rolling(14).mean()

        ENTRY_START = time_obj(9, 30)
        NO_NEW_ENTRIES = time_obj(14, 45)
        HARD_SQUARE_OFF = time_obj(15, 15)

        spread_delta = 1.0 if execution_mode == "futures" else (0.5 if "buying" in execution_mode or "selling" in execution_mode else 0.25)

        current_capital = capital
        peak_capital = capital
        max_drawdown = 0.0
        
        trades = []
        open_position = None
        capital_history = [capital] * len(df)

        for i in range(14, len(df)):
            row = df.loc[i]
            price = row["close"]
            dt_str = row["datetime"]
            candle_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").time()
            atr = row['atr'] if not pd.isna(row['atr']) else 50.0

            signal = check_bot3_signals(df, i)

            if open_position is not None and candle_time >= HARD_SQUARE_OFF:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    gross_pnl = spot_diff * spread_delta * total_qty_units
                else:
                    gross_pnl = -spot_diff * spread_delta * total_qty_units
                
                exit_value = abs(open_position["entry_spread"] + (spot_diff * spread_delta)) * total_qty_units
                exit_side = "BUY" if open_position["type"] == "SHORT" else "SELL"
                exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side, legs=2 if 'spread' in execution_mode else 1, apply_brokerage=apply_brokerage, is_spread=('spread' in execution_mode))

                net_pnl = gross_pnl - open_position["entry_fee"] - exit_fee
                current_capital += (open_position["margin_blocked"] + gross_pnl - exit_fee)
                
                trades.append({
                    "id": len(trades) + 1,
                    "direction": open_position["type"],
                    "qty": total_qty_units,
                    "entry_time": open_position["datetime"],
                    "entry_price": round(open_position["entry_spread"], 2),
                    "exit_time": dt_str,
                    "exit_price": round(open_position["entry_spread"] + (spot_diff * spread_delta), 2),
                    "gross_pnl": round(gross_pnl, 2),
                    "net_pnl": round(net_pnl, 2),
                    "exit_reason": "EOD Square-Off"
                })
                open_position = None

            elif open_position is not None:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    temp_gross_pnl = spot_diff * spread_delta * total_qty_units
                else:
                    temp_gross_pnl = -spot_diff * spread_delta * total_qty_units
                
                exit_reason = ""
                should_exit = False
                
                # Dynamic ATR Trailing Stop Math (Perfect Math Trail)
                if open_position["type"] == "LONG":
                    mfe = max(open_position.get("mfe", price), price)
                    open_position["mfe"] = mfe
                    # Trail by 3 ATR
                    trail_stop_level = mfe - (3.0 * atr)
                    if price < trail_stop_level:
                        should_exit = True
                        exit_reason = "Dynamic ATR Trail"
                else:
                    mfe = min(open_position.get("mfe", price), price)
                    open_position["mfe"] = mfe
                    trail_stop_level = mfe + (3.0 * atr)
                    if price > trail_stop_level:
                        should_exit = True
                        exit_reason = "Dynamic ATR Trail"
                        
                # 15% PnL Hard Stop
                entry_value = open_position["entry_spread"] * total_qty_units
                if entry_value > 0 and temp_gross_pnl <= -0.15 * entry_value:
                    should_exit = True
                    exit_reason = "15% PnL Stop"
                    
                # Reversal Exit (SAR)
                if open_position["type"] == "LONG" and signal == "SHORT":
                    should_exit = True
                    exit_reason = "SAR Reversal"
                elif open_position["type"] == "SHORT" and signal == "LONG":
                    should_exit = True
                    exit_reason = "SAR Reversal"
                
                if i == len(df) - 1:
                    should_exit = True
                    exit_reason = "End of Data"
                    
                if should_exit:
                    exit_value = abs(open_position["entry_spread"] + (spot_diff * spread_delta)) * total_qty_units
                    exit_side = "BUY" if open_position["type"] == "SHORT" else "SELL"
                    exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side, legs=2 if 'spread' in execution_mode else 1, apply_brokerage=apply_brokerage, is_spread=('spread' in execution_mode))

                    gross_pnl = temp_gross_pnl
                    net_pnl = gross_pnl - open_position["entry_fee"] - exit_fee
                    current_capital += (open_position["margin_blocked"] + gross_pnl - exit_fee)
                    
                    trades.append({
                        "id": len(trades) + 1,
                        "direction": open_position["type"],
                        "qty": total_qty_units,
                        "entry_time": open_position["datetime"],
                        "entry_price": round(open_position["entry_spread"], 2),
                        "exit_time": dt_str,
                        "exit_price": round(open_position["entry_spread"] + (spot_diff * spread_delta), 2),
                        "gross_pnl": round(gross_pnl, 2),
                        "net_pnl": round(net_pnl, 2),
                        "exit_reason": exit_reason
                    })
                    open_position = None

            # New Entry Logic (SAR also enters new trade after exit)
            if open_position is None and signal in ["LONG", "SHORT"] and i < len(df) - 1:
                in_entry_window = (ENTRY_START <= candle_time <= NO_NEW_ENTRIES)
                if in_entry_window:
                    margin_per_unit = price * 0.10 if execution_mode == "futures" else (price * 0.01 if execution_mode in ["options_buying", "options_selling"] else price * 0.005)
                    entry_spread = price if execution_mode == "futures" else (price * 0.01 if execution_mode in ["options_buying", "options_selling"] else price * 0.005)
                    
                    margin_required = margin_per_unit * total_qty_units
                    entry_value = entry_spread * total_qty_units
                    
                    entry_side = "SELL" if signal == "SHORT" else "BUY"
                    entry_fee, fee_breakdown = calculate_statutory_charges(charges_profile, entry_value, total_qty_units, entry_side, legs=2 if 'spread' in execution_mode else 1, apply_brokerage=apply_brokerage, is_spread=('spread' in execution_mode))
                    
                    if current_capital >= (margin_required + entry_fee):
                        current_capital -= (margin_required + entry_fee)
                        open_position = {
                            "type": signal,
                            "entry_spot": price,
                            "entry_spread": entry_spread,
                            "datetime": dt_str,
                            "entry_fee": entry_fee,
                            "margin_blocked": margin_required,
                            "mfe": price
                        }

            effective_capital = current_capital
            if open_position is not None:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    unrealized_pnl = spot_diff * spread_delta * total_qty_units
                else:
                    unrealized_pnl = -spot_diff * spread_delta * total_qty_units
                effective_capital += (open_position["margin_blocked"] + unrealized_pnl)
            
            capital_history[i] = effective_capital
            if effective_capital > peak_capital:
                peak_capital = effective_capital
            drawdown = (peak_capital - effective_capital) / peak_capital * 100.0 if peak_capital > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        df["capital_curve"] = capital_history
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t["net_pnl"] > 0)
        losing_trades = sum(1 for t in trades if t["net_pnl"] < 0)
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
        gross_profits = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        gross_losses = sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
        profit_factor = (gross_profits / abs(gross_losses)) if gross_losses != 0 else (gross_profits if gross_profits > 0 else 1.0)
        net_pnl = sum(t["net_pnl"] for t in trades)
        roi = (net_pnl / capital) * 100.0
        avg_trade_pnl = (net_pnl / total_trades) if total_trades > 0 else 0.0

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

        return True, {
            "status": "success",
            "symbol": symbol,
            "strategy": "bot3_dtc_sar",
            "metrics": metrics,
            "trades": trades,
            "chart_data": [] # Omitted for speed
        }, 200

    except Exception as e:
        import traceback
        logger.error(f"Error in Bot 3 NSE backtest: {traceback.format_exc()}")
        return False, {"status": "error", "message": str(e)}, 500



def run_bot4_backtest(params: dict) -> tuple[bool, dict, int]:
    try:
        import traceback
        import logging
        import duckdb
        import os
        from datetime import datetime, time as time_obj
        from database.historify_db import get_ohlcv
        from services.backtest_service import calculate_statutory_charges

        logger = logging.getLogger(__name__)
        
        symbol = params.get("symbol", "NIFTY")
        exchange = params.get("exchange", "NSE")
        interval = "1m"
        start_date_str = params.get("start_date")
        end_date_str = params.get("end_date")
        capital = float(params.get("capital", 800000.0))
        qty_param = int(params.get("lot_size", 25))
        target_type = params.get("target_type", "fixed_1600")
        execution_mode = params.get("execution_mode", "options_selling")
        apply_brokerage = params.get("apply_brokerage", True)

        # Force bot4 execution mode and charges profile
        execution_mode = "options_selling"
        charges_profile = "fo_options"
        
        start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp()) if start_date_str else None
        end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp()) if end_date_str else None

        df = get_ohlcv(
            symbol,
            exchange="NSE_INDEX" if exchange == "NSE" else ("BSE_INDEX" if exchange == "BSE" else exchange),
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts
        )
        if df.empty:
            return False, {"status": "error", "message": "No historical data found"}, 404

        df = df.sort_values("timestamp").reset_index(drop=True)
        df["datetime"] = df["timestamp"].apply(lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"))
        df['dt'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
        
        # Bot 4 Strategy Parameters
        GAP_PCT = 0.005
        MTM_START = 0.0025
        MTM_TRAIL_DD = 0.30
        PROFIT_TARGET_PER_LOT = float(params.get("profit_target_amount", 1600))
        PROFIT_TARGET_PCT = float(params.get("profit_target_pct", 0.005))
        sl_pct = 0.01

        grouped = df.groupby(df['dt'].dt.date)

        # --- Load real ATM premiums from options_daily_premiums (NSE Bhav Copy) ---
        real_premiums = {}  # date -> {ce_open, pe_open, straddle_open, dte}
        try:
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "historify.duckdb")
            if os.path.exists(db_path):
                bhav_con = duckdb.connect(db_path, read_only=True)
                bhav_rows = bhav_con.execute(
                    "SELECT date, ce_open, pe_open, straddle_open, dte FROM options_daily_premiums WHERE symbol=? AND date BETWEEN ? AND ? ORDER BY date",
                    [symbol, start_date_str, end_date_str]
                ).fetchall()
                bhav_con.close()
                for row in bhav_rows:
                    real_premiums[row[0]] = {
                        "ce_open": row[1], "pe_open": row[2],
                        "straddle_open": row[3], "dte": row[4] or 7
                    }
                logger.info(f"Bot4 backtest: loaded {len(real_premiums)} days of real NSE Bhav Copy premiums for {symbol}")
        except Exception as bhav_err:
            logger.warning(f"Bot4 backtest: could not load real premiums ({bhav_err}), using synthetic model")
        # -------------------------------------------------------------------------

        current_capital = capital
        peak_capital = capital
        max_drawdown = 0.0
        
        trades = []
        capital_history = []
        
        prev_close = None

        for date, day_df in grouped:
            if len(day_df) < 200:
                if len(day_df) > 0:
                    prev_close = float(day_df.iloc[-1]['close'])
                # Append flat capital for missing days
                for _ in range(len(day_df)):
                    capital_history.append(current_capital)
                continue

            day_open = float(day_df.iloc[0]['open'])
            day_close = float(day_df.iloc[-1]['close'])

            if prev_close is None:
                prev_close = day_close
                for _ in range(len(day_df)):
                    capital_history.append(current_capital)
                continue

            gap = abs(day_open - prev_close) / prev_close
            if gap > GAP_PCT:
                prev_close = day_close
                for _ in range(len(day_df)):
                    capital_history.append(current_capital)
                continue

            # Determine Lot Size (Per Leg)
            qty = qty_param
            
            # Calculate Deployed Capital for MTM targets based on lot size
            margin_per_lot = 160000 if symbol == "BANKNIFTY" else (100000 if symbol == "SENSEX" else 160000)
            base_lot_size = 30 if symbol == "BANKNIFTY" else (10 if symbol == "SENSEX" else (40 if symbol == "FINNIFTY" else 65))
            deployed_capital = max(margin_per_lot, (qty / base_lot_size) * margin_per_lot)
            
            if target_type == "fixed_1600":
                target_profit = max(1, (qty / base_lot_size)) * PROFIT_TARGET_PER_LOT
            else:
                target_profit = deployed_capital * PROFIT_TARGET_PCT

            ce_entry = pe_entry = None
            ce_sl = pe_sl = None
            ce_open = pe_open = False
            entered = aborted = False
            
            rolls_done = 0
            max_rolls = 1
            total_legs_traded = 4

            peak_mtm = 0.0
            day_pnl = 0.0
            
            entry_datetime = None
            exit_datetime = None
            exit_reason = "EOD Square Off"

            # --- Determine real premium for today if available ---
            real_day = real_premiums.get(date)
            use_real_premium = real_day is not None
            # ---------------------------------------------------------

            for idx, row in day_df.iterrows():
                t = row['dt'].time()
                price = float(row['close'])
                ts = row['timestamp']
                dt_str = row['datetime']

                if t.hour == 9 and t.minute == 21 and not entered:
                    spot_at_entry = price
                    if use_real_premium:
                        # Real NSE Bhav Copy ATM option opening premiums
                        ce_entry = real_day["ce_open"]
                        pe_entry = real_day["pe_open"]
                    else:
                        # Synthetic fallback: 1% of spot per leg
                        ce_entry = price * 0.01
                        pe_entry = price * 0.01
                    ce_sl = price * (1 + sl_pct)
                    pe_sl = price * (1 - sl_pct)
                    ce_open = pe_open = True
                    entered = True
                    entry_datetime = dt_str
                    
                    # Deduct entry fees conceptually (calculated properly at EOD)
                    capital_history.append(current_capital)
                    continue

                if not entered:
                    capital_history.append(current_capital)
                    continue
                    
                if aborted:
                    capital_history.append(current_capital + day_pnl)
                    continue

                # Delta P&L: spot move × delta(0.5) × qty
                # For short straddle: CE loses when spot rises, PE gains, and vice versa
                spot_at_entry_ref = spot_at_entry if entered else price
                spot_move = price - spot_at_entry_ref
                ce_mtm = -spot_move * 0.5 * qty if ce_open else 0.0   # short CE loses when spot rises
                pe_mtm =  spot_move * 0.5 * qty if pe_open else 0.0   # short PE gains when spot rises

                # --- Options Simulation: Theta + Gamma (calibrated to real premium if available) ---
                minutes_held = (t.hour * 60 + t.minute) - (9 * 60 + 21)
                if minutes_held < 0: minutes_held = 0

                if use_real_premium:
                    # Real premium from NSE Bhav Copy — theta modeled as % decay over DTE
                    dte = max(real_day["dte"], 1)
                    total_day_mins = 375.0  # 9:15 to 15:30
                    # Intraday theta: roughly 1/DTE of total premium decays per day (linearly distributed)
                    straddle_prem = real_day["straddle_open"] * qty
                    daily_theta = straddle_prem / dte
                    theta_profit = (minutes_held / total_day_mins) * daily_theta

                    # Gamma: per-lot straddle premium × gamma factor
                    spot_divergence = abs(price - spot_at_entry_ref)
                    divergence_pct = spot_divergence / spot_at_entry_ref if spot_at_entry_ref > 0 else 0
                    gamma_loss = (divergence_pct / 0.01) * (straddle_prem * 0.12)
                else:
                    # Synthetic fallback: 1% of spot as total premium
                    total_premium = (ce_entry + pe_entry) * qty
                    theta_profit = (minutes_held / 360.0) * (total_premium * 0.20)
                    spot_divergence = abs(price - spot_at_entry_ref)
                    divergence_pct = spot_divergence / spot_at_entry_ref if spot_at_entry_ref > 0 else 0
                    gamma_loss = (divergence_pct / 0.01) * (total_premium * 0.15)

                simulated_options_pnl = theta_profit - gamma_loss

                # Scale by how many legs are still open
                open_legs_ratio = (1 if ce_open else 0) + (1 if pe_open else 0)
                simulated_options_pnl = simulated_options_pnl * (open_legs_ratio / 2.0)
                # ---------------------------------------------------------------------------------

                live_mtm = day_pnl + ce_mtm + pe_mtm + simulated_options_pnl

                if live_mtm > peak_mtm:
                    peak_mtm = live_mtm

                # Check SL
                if ce_open and price >= ce_sl:
                    ce_open = False
                    day_pnl += (ce_entry - ce_sl) * 0.5 * qty
                    if rolls_done < max_rolls:
                        # Roll PE up
                        if pe_open:
                            day_pnl += (price - pe_entry) * 0.5 * qty + simulated_options_pnl / 2.0
                        pe_entry = price
                        pe_sl = price * (1 - sl_pct)
                        pe_open = True
                        rolls_done += 1
                        total_legs_traded += 2
                    elif not pe_open:
                        aborted = True
                        exit_datetime = dt_str
                        exit_reason = "Both Legs SL Hit"

                if pe_open and price <= pe_sl:
                    pe_open = False
                    day_pnl += (pe_sl - pe_entry) * 0.5 * qty
                    if rolls_done < max_rolls:
                        # Roll CE down
                        if ce_open:
                            day_pnl += (ce_entry - price) * 0.5 * qty + simulated_options_pnl / 2.0
                        ce_entry = price
                        ce_sl = price * (1 + sl_pct)
                        ce_open = True
                        rolls_done += 1
                        total_legs_traded += 2
                    elif not ce_open:
                        aborted = True
                        exit_datetime = dt_str
                        exit_reason = "Both Legs SL Hit"

                # Take Profit Target (Guaranteed Green Day)
                if not aborted and live_mtm >= target_profit:
                    aborted = True
                    day_pnl = live_mtm
                    ce_open = pe_open = False
                    exit_datetime = dt_str
                    exit_reason = "Profit Target Hit"

                # Check MTM trail
                if not aborted and peak_mtm > deployed_capital * MTM_START:
                    if live_mtm < peak_mtm * (1 - MTM_TRAIL_DD):
                        aborted = True
                        day_pnl = live_mtm
                        ce_open = pe_open = False
                        exit_datetime = dt_str
                        exit_reason = "MTM Trailing SL"

                # Check Max loss
                if not aborted and live_mtm < -(deployed_capital * 0.02):
                    aborted = True
                    day_pnl = -(deployed_capital * 0.02)
                    ce_open = pe_open = False
                    exit_datetime = dt_str
                    exit_reason = "Max Daily Loss Hit"

                # EOD Exit
                if not aborted and t.hour == 15 and t.minute >= 15:
                    day_pnl = live_mtm
                    ce_open = pe_open = False
                    aborted = True
                    exit_datetime = dt_str
                    exit_reason = "EOD Square Off"
                
                # Append running capital state
                if aborted:
                    capital_history.append(current_capital + day_pnl)
                else:
                    capital_history.append(current_capital + live_mtm)

                # Drawdown tracker
                if capital_history[-1] > peak_capital:
                    peak_capital = capital_history[-1]
                drawdown = (peak_capital - capital_history[-1]) / peak_capital * 100.0 if peak_capital > 0 else 0.0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

            prev_close = day_close
            
            if not entered:
                continue

            if exit_datetime is None:
                exit_datetime = day_df.iloc[-1]['datetime']

            # Calculate statutory charges for straddle selling
            # Use real premium if available, else fall back to synthetic
            if use_real_premium and real_day:
                premium_per_leg = (real_day["ce_open"] + real_day["pe_open"]) / 2.0
            else:
                premium_per_leg = ce_entry  # ce_entry is already the option premium (real or synthetic)
            
            entry_legs = total_legs_traded // 2
            exit_legs = total_legs_traded // 2
            
            sell_value = premium_per_leg * qty * entry_legs
            # Options selling usually buys them back cheaper if profitable
            buy_value = (premium_per_leg * qty * exit_legs) - day_pnl 
            if buy_value < 0:
                buy_value = 0 # Cannot be negative
                
            entry_fee, entry_fee_breakdown = calculate_statutory_charges(charges_profile, sell_value, qty * entry_legs, "SELL", legs=entry_legs, apply_brokerage=apply_brokerage)
            exit_fee, exit_fee_breakdown = calculate_statutory_charges(charges_profile, buy_value, qty * exit_legs, "BUY", legs=exit_legs, apply_brokerage=apply_brokerage)
            total_charges = entry_fee + exit_fee
            
            combined_breakdown = {k: entry_fee_breakdown.get(k, 0) + exit_fee_breakdown.get(k, 0) for set_ in (entry_fee_breakdown, exit_fee_breakdown) for k in set_}

            net_pnl = day_pnl - total_charges
            current_capital += net_pnl
            
            # Reconcile history to avoid discontinuities
            capital_history[-1] = current_capital

            trades.append({
                "id": len(trades) + 1,
                "direction": "SELL", # Short Straddle
                "qty": qty, # Per-leg quantity for display
                "entry_time": entry_datetime,
                "entry_price": round(ce_entry, 2), # Using spot reference
                "exit_time": exit_datetime,
                "exit_price": round(ce_entry - (day_pnl / (qty * 2)), 2) if day_pnl != -(deployed_capital * 0.02) else round(ce_entry + (abs(day_pnl) / (qty * 2)), 2),
                "entry_fee": round(entry_fee, 2),
                "exit_fee": round(exit_fee, 2),
                "gross_pnl": round(day_pnl, 2),
                "net_pnl": round(net_pnl, 2),
                "pnl_pct": round((net_pnl / capital) * 100.0, 2),
                "exit_reason": exit_reason,
                "fee_breakdown": combined_breakdown
            })

        df["capital_curve"] = capital_history
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t["net_pnl"] > 0)
        losing_trades = sum(1 for t in trades if t["net_pnl"] < 0)
        win_rate = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0
        gross_profits = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        gross_losses = sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
        profit_factor = (gross_profits / abs(gross_losses)) if gross_losses != 0 else (gross_profits if gross_profits > 0 else 1.0)
        net_pnl_total = sum(t["net_pnl"] for t in trades)
        roi = (net_pnl_total / capital) * 100.0
        avg_trade_pnl = (net_pnl_total / total_trades) if total_trades > 0 else 0.0

        metrics = {
            "initial_capital": round(capital, 2),
            "final_capital": round(capital + net_pnl_total, 2),
            "net_pnl": round(net_pnl_total, 2),
            "roi_pct": round(roi, 2),
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "avg_trade_pnl": round(avg_trade_pnl, 2)
        }
        
        # Prepare chart data natively
        chart_data = []
        for i, row in df.iterrows():
            if pd.isna(row["open"]):
                continue
            chart_data.append({
                "timestamp": int(row["timestamp"]),
                "datetime": row["datetime"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if "volume" in row and pd.notna(row["volume"]) else 0.0,
                "capital": float(row["capital_curve"]) if "capital_curve" in row and pd.notna(row["capital_curve"]) else current_capital
            })

        return True, {
            "status": "success",
            "symbol": symbol,
            "strategy": "bot4_straddle_seller",
            "metrics": metrics,
            "trades": trades,
            "chart_data": chart_data
        }, 200

    except Exception as e:
        import traceback
        logger.error(f"Error in Bot 4 backtest: {traceback.format_exc()}")
        return False, {"status": "error", "message": str(e)}, 500

