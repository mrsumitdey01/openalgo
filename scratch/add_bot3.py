import os

# --- NSE BOT 3 ---
bot3_nse_code = """
def run_bot3_backtest(params: dict) -> tuple[bool, dict, int]:
    try:
        import pandas as pd
        import numpy as np
        from datetime import datetime, time as time_obj
        from api.data import get_ohlcv
        from strategies.scripts.bot1_hull_dtc_ribbon import DTCRibbon
        from strategies.scripts.bot3_dtc_sar import check_bot3_signals
        from utils.logger import setup_logger
        
        logger = setup_logger("bot3_nse_backtest")
        
        symbol = params.get("symbol", "BANKNIFTY")
        exchange = params.get("exchange", "NSE_INDEX")
        interval = params.get("interval", "1minute")
        start_date_str = params.get("start_date")
        end_date_str = params.get("end_date")
        capital = float(params.get("capital", 100000.0))
        execution_mode = params.get("execution_mode", "options_spread")
        apply_brokerage = params.get("apply_brokerage", True)

        charges_profile = "fo_futures" if execution_mode == "futures" else "fo_options"
        total_qty_units = int(params.get("lot_size", 1))

        start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp()) if start_date_str else None
        end_ts = int(datetime.strptime(end_date_str, "%Y-%m-%d").replace(hour=23, minute=59, second=59).timestamp()) if end_date_str else None

        df = get_ohlcv(symbol, exchange, interval, start_ts, end_ts)
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
                exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side, legs=2 if 'spread' in execution_mode else 1, apply_brokerage=apply_brokerage)

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
                    exit_fee, fee_breakdown = calculate_statutory_charges(charges_profile, exit_value, total_qty_units, exit_side, legs=2 if 'spread' in execution_mode else 1, apply_brokerage=apply_brokerage)

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
                    entry_fee, fee_breakdown = calculate_statutory_charges(charges_profile, entry_value, total_qty_units, entry_side, legs=2 if 'spread' in execution_mode else 1, apply_brokerage=apply_brokerage)
                    
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
"""

bot3_mcx_code = bot3_nse_code.replace("run_bot3_backtest", "run_bot3_mcx_backtest").replace("NSE", "MCX").replace("BANKNIFTY", "CRUDEOIL").replace("NSE_INDEX", "MCX")
bot3_mcx_code = bot3_mcx_code.replace('charges_profile = "fo_futures" if execution_mode == "futures" else "fo_options"', 'charges_profile = "mcx_futures" if execution_mode == "futures" else "mcx_options"')
bot3_mcx_code = bot3_mcx_code.replace("ENTRY_START = time_obj(9, 30)", "ENTRY_START = time_obj(10, 0)")
bot3_mcx_code = bot3_mcx_code.replace("NO_NEW_ENTRIES = time_obj(14, 45)", "NO_NEW_ENTRIES = time_obj(23, 0)")
bot3_mcx_code = bot3_mcx_code.replace("HARD_SQUARE_OFF = time_obj(15, 15)", "HARD_SQUARE_OFF = time_obj(23, 15)")

with open(r"C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\services\backtest_service.py", "a") as f:
    f.write("\n\n" + bot3_nse_code)

with open(r"C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\services\backtest_mcx_service.py", "a") as f:
    f.write("\n\n" + bot3_mcx_code)

print("Bot 3 appended to services!")
