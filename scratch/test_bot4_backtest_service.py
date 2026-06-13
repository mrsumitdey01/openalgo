import pandas as pd
import numpy as np

def run_bot4_backtest(params: dict) -> tuple[bool, dict, int]:
    try:
        import traceback
        import logging
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
        execution_mode = params.get("execution_mode", "options_selling")
        apply_brokerage = params.get("apply_brokerage", True)

        # Force bot4 execution mode and charges profile
        execution_mode = "options_selling"
        charges_profile = "fo_options"
        
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
        df['dt'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
        
        # Bot 4 Strategy Parameters
        GAP_PCT = 0.005
        MTM_START = 0.0025
        MTM_TRAIL_DD = 0.50
        sl_pct = 0.004

        grouped = df.groupby(df['dt'].dt.date)

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

            # Determine Lot Size
            qty = 32 if date.weekday() == 2 else 65

            ce_entry = pe_entry = None
            ce_sl = pe_sl = None
            ce_open = pe_open = False
            entered = aborted = False

            peak_mtm = 0.0
            day_pnl = 0.0
            
            entry_datetime = None
            exit_datetime = None
            exit_reason = "EOD Square Off"

            for idx, row in day_df.iterrows():
                t = row['dt'].time()
                price = float(row['close'])
                ts = row['timestamp']
                dt_str = row['datetime']

                if t.hour == 9 and t.minute == 21 and not entered:
                    ce_entry = pe_entry = price
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

                ce_mtm = (ce_entry - price) * 0.5 * qty if ce_open else 0.0
                pe_mtm = (price - pe_entry) * 0.5 * qty if pe_open else 0.0
                live_mtm = day_pnl + ce_mtm + pe_mtm

                if live_mtm > peak_mtm:
                    peak_mtm = live_mtm

                # Check SL
                if ce_open and price >= ce_sl:
                    ce_open = False
                    day_pnl += (ce_entry - ce_sl) * 0.5 * qty
                    if not pe_open:
                        aborted = True
                        exit_datetime = dt_str
                        exit_reason = "Both Legs SL Hit"

                if pe_open and price <= pe_sl:
                    pe_open = False
                    day_pnl += (pe_entry - pe_sl) * 0.5 * qty
                    if not ce_open:
                        aborted = True
                        exit_datetime = dt_str
                        exit_reason = "Both Legs SL Hit"

                # Check MTM trail
                if not aborted and peak_mtm > capital * MTM_START:
                    if live_mtm < peak_mtm * (1 - MTM_TRAIL_DD):
                        aborted = True
                        if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                        if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
                        ce_open = pe_open = False
                        exit_datetime = dt_str
                        exit_reason = "MTM Trailing SL"

                # Check Max loss
                if not aborted and live_mtm < -(capital * 0.02):
                    aborted = True
                    day_pnl = -(capital * 0.02)
                    ce_open = pe_open = False
                    exit_datetime = dt_str
                    exit_reason = "Max Daily Loss Hit"

                # EOD Exit
                if not aborted and t.hour == 15 and t.minute == 15:
                    if ce_open: day_pnl += (ce_entry - price) * 0.5 * qty
                    if pe_open: day_pnl += (price - pe_entry) * 0.5 * qty
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
            premium_per_leg = ce_entry * 0.01  # Synthesize options premium as 1% of spot
            sell_value = premium_per_leg * qty * 2
            # Options selling usually buys them back cheaper if profitable
            buy_value = (premium_per_leg * qty * 2) - day_pnl 
            if buy_value < 0:
                buy_value = 0 # Cannot be negative
                
            entry_fee, _ = calculate_statutory_charges(charges_profile, sell_value, qty * 2, "SELL", legs=2, apply_brokerage=apply_brokerage)
            exit_fee, _ = calculate_statutory_charges(charges_profile, buy_value, qty * 2, "BUY", legs=2, apply_brokerage=apply_brokerage)
            total_charges = entry_fee + exit_fee

            net_pnl = day_pnl - total_charges
            current_capital += net_pnl
            
            # Reconcile history to avoid discontinuities
            capital_history[-1] = current_capital

            trades.append({
                "id": len(trades) + 1,
                "direction": "SELL", # Short Straddle
                "qty": qty * 2, # Combined lots
                "entry_time": entry_datetime,
                "entry_price": round(ce_entry, 2), # Using spot reference
                "exit_time": exit_datetime,
                "exit_price": round(ce_entry - (day_pnl / (qty * 2)), 2) if day_pnl != -(capital * 0.02) else round(ce_entry + (abs(day_pnl) / (qty * 2)), 2),
                "gross_pnl": round(day_pnl, 2),
                "net_pnl": round(net_pnl, 2),
                "exit_reason": exit_reason
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
