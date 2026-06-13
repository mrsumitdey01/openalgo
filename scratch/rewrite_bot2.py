import sys

path = 'services/backtest_mcx_service.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

parts = content.split('def run_bot2_mcx_backtest(params: dict) -> tuple[bool, dict, int]:')
if len(parts) == 2:
    top = parts[0]
    
    bot2_replacement = """def run_bot2_mcx_backtest(params: dict) -> tuple[bool, dict, int]:
    try:
        from strategies.scripts.bot2_mcx_bb_trend import BollingerTrendFilter, check_signals
        from datetime import time as time_obj
        from database.historify_db import get_ohlcv
        from config.charges import calculate_statutory_charges
        from utils.logger import get_logger
        from datetime import datetime
        logger = get_logger()

        symbol = params.get("symbol", "CRUDEOIL").strip().upper()
        exchange = params.get("exchange", "MCX").strip().upper()
        interval = "1m"
        start_date_str = params.get("start_date")
        end_date_str = params.get("end_date")
        capital = float(params.get("capital", 100000.0))
        execution_mode = params.get("execution_mode", "options_spread")

        charges_profile = "mcx_futures" if execution_mode == "futures" else "mcx_options"
        lot_size = int(params.get("lot_size", 1))

        # Crude oil unit size
        unit_size = 100 if symbol == "CRUDEOIL" else 1

        start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp()) if start_date_str else None
        end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp()) if end_date_str else None

        df = get_ohlcv(
            symbol=symbol,
            exchange="MCX_INDEX" if exchange == "MCX" else exchange,
            interval=interval,
            start_timestamp=start_ts,
            end_timestamp=end_ts
        )

        if df.empty:
            return False, {"status": "error", "message": "No historical data found"}, 404

        df = df.sort_values("timestamp").reset_index(drop=True)
        df["datetime"] = df["timestamp"].apply(lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"))

        bb_trend = BollingerTrendFilter(bb_period=20, bb_std=2.0, rsi_period=14, ema_period=200)
        df = bb_trend.compute(df)

        ENTRY_START = time_obj(10, 0)
        NO_NEW_ENTRIES = time_obj(22, 0)
        HARD_SQUARE_OFF = time_obj(22, 30)

        spread_delta = 1.0 if execution_mode == "futures" else (0.5 if "buying" in execution_mode or "selling" in execution_mode else 0.25)
        total_qty_units = lot_size * unit_size

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

            # EOD Hard Square-Off
            if open_position is not None and candle_time >= HARD_SQUARE_OFF:
                spot_diff = price - open_position["entry_spot"]
                if open_position["type"] == "LONG":
                    gross_pnl = spot_diff * spread_delta * total_qty_units
                else:
                    gross_pnl = -spot_diff * spread_delta * total_qty_units
                
                exit_value = abs(open_position["entry_spread"] + (spot_diff * spread_delta)) * total_qty_units
                exit_side = "BUY" if open_position["type"] == "SHORT" else "SELL"
                exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side)

                net_pnl = gross_pnl - open_position["entry_fee"] - exit_fee
                current_capital += (open_position["margin_blocked"] + gross_pnl - exit_fee)
                
                trades.append({
                    "id": len(trades) + 1,
                    "direction": open_position["type"],
                    "qty": lot_size,
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

            # Position Exit Logic (Dynamic trailing stops, NO structural/fixed pnl stops)
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
                    
                # Update Max Favorable Excursion
                if excursion > open_position["mfe"]:
                    open_position["mfe"] = excursion
                    
                mfe = open_position["mfe"]
                should_exit = False
                exit_reason = ""
                
                # Dynamic rules
                if signal in ["EXIT_LONG", "EXIT_SHORT"]:
                    should_exit = True
                    exit_reason = "Bot Signal Rev"
                elif mfe >= 50.0 and excursion <= mfe - 25.0:  # Trailing stop activated after 50pts, trails by 25pts
                    should_exit = True
                    exit_reason = "Trailing Stop"
                elif excursion <= -35.0:  # Hard stop at 35 points
                    should_exit = True
                    exit_reason = "Hard Stop"
                elif i == len(df) - 1:
                    should_exit = True
                    exit_reason = "End of Data"

                if should_exit:
                    exit_value = abs(current_spread_val * total_qty_units)
                    exit_side = "BUY" if open_position["type"] == "SHORT" else "SELL"
                    exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side)

                    net_pnl = temp_gross_pnl - open_position["entry_fee"] - exit_fee
                    current_capital += (open_position["margin_blocked"] + temp_gross_pnl - exit_fee)

                    trades.append({
                        "id": len(trades) + 1,
                        "direction": open_position["type"],
                        "qty": lot_size,
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

            # Position Entry Logic
            elif signal in ["LONG", "SHORT"] and i < len(df) - 1:
                in_entry_window = (ENTRY_START <= candle_time <= NO_NEW_ENTRIES)
                if in_entry_window:
                    entry_spread = price * (0.005 if execution_mode == "options_spread" else 1.0)
                    margin_per_unit = price * (0.005 if execution_mode == "options_spread" else 0.10)
                    
                    margin_required = margin_per_unit * total_qty_units
                    entry_value = entry_spread * total_qty_units

                    entry_side = "SELL" if signal == "SHORT" else "BUY"
                    entry_fee, fee_breakdown = calculate_statutory_charges(charges_profile, entry_value, total_qty_units, entry_side)

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

            # Tracking
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

        # Chart Data
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
            "strategy": "bot2_mcx_bb_trend",
            "metrics": metrics,
            "trades": trades,
            "chart_data": chart_data
        }
        return True, response, 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, {"status": "error", "message": str(e)}, 500
"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(top + bot2_replacement)
    print("Rewrote bot2 backtester entirely")
else:
    print("Could not split!")
