import logging
import importlib

logger = logging.getLogger(__name__)

def run_scanner_backtest(params: dict) -> tuple[bool, dict, int]:
    """
    Run Bot 6 or Bot 6b Scanner backtest over multiple symbols simultaneously.
    """
    try:
        bot_id = params.get("bot_id", "bot6")
        if bot_id not in ["bot6", "bot6b", "bot6c"]:
            return False, {"status": "error", "message": f"Unsupported scanner bot: {bot_id}"}, 400
            
        engine_module = importlib.import_module(f"{bot_id}.backtest_engine")
        config_module = importlib.import_module(f"{bot_id}.config")
        
        run_backtest = getattr(engine_module, "run_backtest")
        WATCHLIST = getattr(config_module, "WATCHLIST")

        start_date = params.get("start_date")
        end_date = params.get("end_date")
        total_capital = float(params.get("capital", 500000.0))
        
        symbols = params.get("symbols", WATCHLIST)
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
            
        capital_per_trade = total_capital / 10.0 # 10 open positions max

        trades = run_backtest(
            db_path="db/historify.duckdb",
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            total_capital=total_capital,
            capital_per_trade=capital_per_trade,
        )

        # Format trades to match UI expectations
        for t in trades:
            # Map side to direction
            t["direction"] = "LONG" if t["side"] == "LONG" else "SHORT"
            
            # Simple flat fee for calculation (e.g., 40 Rs per round trip)
            fees = 40.0 
            t["entry_fee"] = 20.0
            t["exit_fee"] = 20.0
            
            t["net_pnl"] = t["gross_pnl"] - fees
            
            # Pnl Pct based on capital deployed
            capital_deployed = t.get("capital_deployed", t["entry_price"] * t["qty"])
            t["pnl_pct"] = round((t["net_pnl"] / capital_deployed) * 100, 2) if capital_deployed > 0 else 0.0

            # Convert pd.Timestamp/date to strings
            t["entry_time"] = str(t["entry_time"])
            t["exit_time"] = str(t["exit_time"])
            t["date"] = str(t["date"])

        # Compute metrics
        net_pnl = sum(t["net_pnl"] for t in trades)
        final_capital = total_capital + net_pnl
        roi_pct = round((net_pnl / total_capital) * 100, 2)
        total_trades = len(trades)
        
        winning_trades = sum(1 for t in trades if t["net_pnl"] > 0)
        losing_trades = total_trades - winning_trades
        win_rate_pct = round((winning_trades / total_trades) * 100, 2) if total_trades > 0 else 0.0
        
        gross_win = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
        gross_loss = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
        profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (99.9 if gross_win > 0 else 0)
        
        avg_trade_pnl = round(net_pnl / total_trades, 2) if total_trades > 0 else 0.0

        # Max drawdown computation
        max_drawdown_pct = 0.0
        peak_capital = total_capital
        current_cap = total_capital
        for t in trades:
            current_cap += t["net_pnl"]
            if current_cap > peak_capital:
                peak_capital = current_cap
            
            dd = (peak_capital - current_cap) / peak_capital * 100
            if dd > max_drawdown_pct:
                max_drawdown_pct = round(dd, 2)

        # Sort trades in reverse chronological order so UI shows newest first
        trades.sort(key=lambda x: x["exit_time"], reverse=True)

        metrics = {
            "initial_capital": total_capital,
            "final_capital": round(final_capital, 2),
            "net_pnl": round(net_pnl, 2),
            "roi_pct": roi_pct,
            "total_trades": total_trades,
            "win_rate_pct": win_rate_pct,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_drawdown_pct,
            "avg_trade_pnl": avg_trade_pnl
        }

        response = {
            "status": "success",
            "strategy": f"{bot_id}_scanner",
            "metrics": metrics,
            "trades": trades,
            "chart_data": [] 
        }

        return True, response, 200

    except Exception as e:
        logger.exception(f"Error in run_scanner_backtest: {e}")
        return False, {"status": "error", "message": str(e)}, 500
