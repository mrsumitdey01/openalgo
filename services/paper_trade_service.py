"""
Paper Trade Service (LIVE ENGINE)
=================================
Runs all 3 bots across all execution modes for NSE and MCX in REAL-TIME.
Uses a background scheduler to evaluate trades minute-by-minute during market hours.
"""

import json
import time
import threading
import traceback
import logging
from datetime import datetime, time as time_obj, timedelta

import numpy as np
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler

from database.historify_db import get_ohlcv
from services.backtest_service import calculate_statutory_charges
from services.quotes_service import get_quotes

logger = logging.getLogger(__name__)

# ─── Global engine state ────────────────────────────────────────────────────
_engine_lock = threading.Lock()
_scheduler = BackgroundScheduler()

_engine_state = {
    "is_active": False,
    "is_running": False,
    "started_at": None,
    "stopped_at": None,
    "last_run_at": None,
    "error": None,
    "accounts": {},     # keyed by account_id  e.g. "bot1_NSE_BANKNIFTY_futures"
}

# ─── Configuration ──────────────────────────────────────────────────────────
PAPER_ACCOUNTS = []

# NSE accounts
for bot in ["bot1", "bot2", "bot3", "bot4"]:
    symbol = "NIFTY" if bot == "bot4" else "BANKNIFTY"
    lot_size = 65 if bot == "bot4" else 30
    capital = 185000.0 if bot == "bot4" else 800000.0
    for mode in ["futures", "options_buying", "options_selling", "options_spread"]:
        PAPER_ACCOUNTS.append({
            "bot": bot,
            "exchange": "NSE",
            "symbol": symbol,
            "db_exchange": "NSE_INDEX",
            "execution_mode": mode,
            "lot_size": lot_size,
            "capital": capital,
        })

# MCX accounts
for bot in ["bot1", "bot2", "bot3", "bot4"]:
    for mode in ["futures", "options_buying", "options_selling", "options_spread"]:
        for sym in ["CRUDEOIL", "GOLDM"]:
            PAPER_ACCOUNTS.append({
                "bot": bot,
                "exchange": "MCX",
                "symbol": sym,
                "db_exchange": "MCX_INDEX",
                "execution_mode": mode,
                "lot_size": 1,
                "capital": 800000.0,
            })

def _account_id(cfg: dict) -> str:
    return f"{cfg['bot']}_{cfg['exchange']}_{cfg['symbol']}_{cfg['execution_mode']}"

def _empty_metrics(capital):
    return {
        "initial_capital": round(capital, 2),
        "final_capital": round(capital, 2),
        "net_pnl": 0.0,
        "roi_pct": 0.0,
        "total_trades": 0,
        "win_rate_pct": 0.0,
        "winning_trades": 0,
        "losing_trades": 0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,
        "avg_trade_pnl": 0.0,
        "profitable_days": 0,
        "total_days": 0,
    }

def _init_account_state(cfg):
    account_id = _account_id(cfg)
    return {
        "account_id": account_id,
        "status": "Waiting for Market Open",
        **cfg,
        "metrics": _empty_metrics(cfg["capital"]),
        "trades": [],
        "open_position": None,
        "last_processed_candle": None,
        "peak_capital": cfg["capital"],
        "max_drawdown": 0.0,
        "current_capital": cfg["capital"],
        "daily_pnl": {}
    }

# ─── Indicator + Signal helpers ─────────────────────────────────────────────

def _prepare_indicators(df: pd.DataFrame, bot: str) -> pd.DataFrame:
    from strategies.scripts.bot1_hull_dtc_ribbon import HullBBI, DTCRibbon
    if bot == "bot1":
        hull = HullBBI(length=21)
        df = hull.compute(df)
        dtc = DTCRibbon()
        df = dtc.compute(df)
    elif bot == "bot2":
        from strategies.scripts.bot2_ema_momentum import EMAMomentum
        ema = EMAMomentum(fast_period=21, slow_period=100)
        df = ema.compute(df)
        dtc = DTCRibbon()
        df = dtc.compute(df)
    elif bot == "bot3":
        dtc = DTCRibbon()
        df = dtc.compute(df)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = true_range.rolling(14).mean()
    return df

def _get_signal(df: pd.DataFrame, i: int, bot: str, position_type: str | None):
    if bot == "bot1":
        from strategies.scripts.bot1_hull_dtc_ribbon import check_signals
        slice_end = i + 1
        slice_start = max(0, slice_end - 6)
        slice_df = df.iloc[slice_start:slice_end]
        return check_signals(slice_df, position_type)
    elif bot == "bot2":
        from strategies.scripts.bot2_ema_momentum import check_signals
        slice_end = i + 1
        slice_start = max(0, slice_end - 6)
        slice_df = df.iloc[slice_start:slice_end]
        return check_signals(slice_df, position_type)
    elif bot == "bot3":
        from strategies.scripts.bot3_dtc_sar import check_bot3_signals
        sig = check_bot3_signals(df, i)
        if position_type is None:
            if sig in ("LONG", "SHORT"):
                return sig
            return None
        elif position_type == "LONG":
            if sig == "SHORT":
                return "EXIT_LONG"
            return None
        elif position_type == "SHORT":
            if sig == "LONG":
                return "EXIT_SHORT"
            return None
    elif bot == "bot4":
        from strategies.scripts.bot4_straddle_seller import check_signals
        slice_end = i + 1
        slice_start = max(0, slice_end - 6)
        slice_df = df.iloc[slice_start:slice_end]
        sig = check_signals(slice_df, position_type)
        if position_type is None:
            if sig == "SHORT_STRADDLE":
                return "SHORT" # To paper trade engine, we just enter a SHORT position (it will synthesize it based on options_selling mode)
        return None
    return None

def _close_position(pos, price, dt_str, reason, spread_delta, charges_profile, execution_mode):
    spot_diff = price - pos["entry_spot"]
    if pos["type"] == "LONG":
        gross_pnl = spot_diff * spread_delta * pos["qty"]
        current_val = pos["entry_spread"] + (spot_diff * spread_delta)
    else:
        gross_pnl = -spot_diff * spread_delta * pos["qty"]
        current_val = pos["entry_spread"] + (spot_diff * spread_delta)

    exit_value = abs(current_val * pos["qty"])
    exit_side = "BUY" if pos["type"] == "SHORT" else "SELL"
    legs = 2 if "spread" in execution_mode else 1
    exit_fee, _ = calculate_statutory_charges(charges_profile, exit_value, pos["qty"], exit_side, legs=legs)
    net_pnl = gross_pnl - pos["entry_fee"] - exit_fee

    return {
        "direction": pos["type"],
        "qty": pos["qty"],
        "entry_time": pos["datetime"],
        "entry_price": round(pos["entry_spread"], 2),
        "exit_time": dt_str,
        "exit_price": round(current_val, 2),
        "gross_pnl": round(gross_pnl, 2),
        "net_pnl": round(net_pnl, 2),
        "entry_fee": round(pos["entry_fee"], 2),
        "exit_fee": round(exit_fee, 2),
        "exit_reason": reason,
    }


# ─── Live Engine Loop ───────────────────────────────────────────────────────

def _run_live_tick():
    """Scheduled job to process live ticks and candles every 30 seconds."""
    global _engine_state
    
    with _engine_lock:
        if not _engine_state["is_active"]:
            return
        _engine_state["is_running"] = True

    try:
        now_dt = datetime.now()
        now_time = now_dt.time()
        now_ts = int(now_dt.timestamp())
        start_ts = now_ts - (7 * 86400) # Fetch last 7 days to ensure enough data for indicators

        for cfg in PAPER_ACCOUNTS:
            with _engine_lock:
                if not _engine_state["is_active"]:
                    break
                acc_id = _account_id(cfg)
                if acc_id not in _engine_state["accounts"]:
                    _engine_state["accounts"][acc_id] = _init_account_state(cfg)
                
                state = _engine_state["accounts"][acc_id]
            
            # Market hours check
            if cfg["exchange"] == "MCX":
                ENTRY_START = time_obj(9, 0)
                NO_NEW_ENTRIES = time_obj(23, 0)
                HARD_SQUARE_OFF = time_obj(23, 30)
            else:
                ENTRY_START = time_obj(9, 30)
                NO_NEW_ENTRIES = time_obj(14, 45)
                HARD_SQUARE_OFF = time_obj(15, 15)
            
            is_market_open = (ENTRY_START <= now_time <= HARD_SQUARE_OFF)
            
            if not is_market_open:
                state["status"] = "Waiting for Market Open"
                # If there are open positions somehow, square them off at EOD
                if state["open_position"] is not None and now_time >= HARD_SQUARE_OFF:
                    # Proceed to square off logic below, otherwise continue
                    pass
                else:
                    continue
                
            state["status"] = "Live Monitoring"

            # 1. Fetch latest exact live price from quotes_service directly from broker API
            success, quote_data, _ = get_quotes(cfg["symbol"], cfg["exchange"])
            live_ltp = quote_data.get("last_price") if success and isinstance(quote_data, dict) else None

            # 2. Fetch recent historical OHLCV from local DB (Historify auto-saves this)
            df = get_ohlcv(
                symbol=cfg["symbol"],
                exchange=cfg["db_exchange"],
                interval="1m",
                start_timestamp=start_ts,
                end_timestamp=now_ts
            )
            
            if df.empty:
                state["status"] = "No Historify Data"
                continue

            df = df.sort_values("timestamp").reset_index(drop=True)
            df["datetime"] = df["timestamp"].apply(
                lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Check for staleness (> 5 minutes old)
            last_candle_dt = datetime.strptime(df.iloc[-1]["datetime"], "%Y-%m-%d %H:%M:%S")
            if (now_dt - last_candle_dt).total_seconds() > 300:
                state["status"] = "Stale Historify Data (>5m)"
            
            df = _prepare_indicators(df, cfg["bot"])
            
            # Use live LTP if available, else last candle close
            current_price = live_ltp if live_ltp and live_ltp > 0 else df.iloc[-1]["close"]
            current_dt_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
            trade_date = now_dt.strftime("%Y-%m-%d")

            open_pos = state["open_position"]
            execution_mode = cfg["execution_mode"]
            
            # Spread delta logic
            if execution_mode == "futures":
                spread_delta = 1.0
            elif execution_mode in ("options_buying", "options_selling"):
                spread_delta = 0.5
            else:
                spread_delta = 0.25

            charges_profile = "fo_futures" if execution_mode == "futures" else "fo_options"
            if cfg["exchange"] == "MCX":
                charges_profile = "mcx_futures" if execution_mode == "futures" else "mcx_options"

            # 3. Check for Exits on Live LTP continuously
            if open_pos is not None:
                spot_diff = current_price - open_pos["entry_spot"]
                if open_pos["type"] == "LONG":
                    temp_gross = spot_diff * spread_delta * open_pos["qty"]
                else:
                    temp_gross = -spot_diff * spread_delta * open_pos["qty"]

                should_exit = False
                exit_reason = ""

                # EOD Square-Off
                if now_time >= HARD_SQUARE_OFF:
                    should_exit, exit_reason = True, "EOD Square-Off"
                
                # PnL stop
                if not should_exit:
                    if execution_mode == "futures":
                        if open_pos["type"] == "LONG" and spot_diff <= -150.0:
                            should_exit, exit_reason = True, "PnL Stop"
                        elif open_pos["type"] == "SHORT" and spot_diff >= 150.0:
                            should_exit, exit_reason = True, "PnL Stop"
                    else:
                        entry_value = open_pos["entry_spread"] * open_pos["qty"]
                        if entry_value > 0 and temp_gross <= -0.15 * entry_value:
                            should_exit, exit_reason = True, "15% PnL Stop"

                # Structural stop
                if not should_exit:
                    struct = open_pos.get("structural_stop")
                    if struct:
                        if open_pos["type"] == "LONG" and current_price < struct:
                            should_exit, exit_reason = True, "Structural Stop"
                        elif open_pos["type"] == "SHORT" and current_price > struct:
                            should_exit, exit_reason = True, "Structural Stop"

                # Check Bot Signal for Exit (only on new closed candles)
                last_candle_time = df.iloc[-1]["datetime"]
                if last_candle_time != state["last_processed_candle"]:
                    signal = _get_signal(df, len(df)-1, cfg["bot"], open_pos["type"])
                    if not should_exit and signal in ("EXIT_LONG", "EXIT_SHORT"):
                        should_exit, exit_reason = True, "Bot Signal"
                    
                if should_exit:
                    trade = _close_position(open_pos, current_price, current_dt_str, exit_reason,
                                            spread_delta, charges_profile, execution_mode)
                    state["current_capital"] += (open_pos["margin_blocked"] + trade["gross_pnl"] - trade["exit_fee"])
                    state["trades"].append(trade)
                    state["daily_pnl"].setdefault(trade_date, 0.0)
                    state["daily_pnl"][trade_date] += trade["net_pnl"]
                    state["open_position"] = None
                    state["last_processed_candle"] = last_candle_time

            # 4. Check for Entries (Only once per new candle)
            last_candle_time = df.iloc[-1]["datetime"]
            if state["open_position"] is None and last_candle_time != state["last_processed_candle"]:
                signal = _get_signal(df, len(df)-1, cfg["bot"], None)
                if signal in ("LONG", "SHORT"):
                    in_window = ENTRY_START <= now_time <= NO_NEW_ENTRIES
                    if in_window:
                        if execution_mode == "futures":
                            margin_per_qty = current_price * 0.10
                            entry_spread = current_price
                        elif execution_mode == "options_buying":
                            margin_per_qty = current_price * 0.01
                            entry_spread = current_price * 0.01
                        elif execution_mode == "options_selling":
                            margin_per_qty = current_price * 0.10
                            entry_spread = current_price * 0.01
                        else:
                            margin_per_qty = current_price * 0.005
                            entry_spread = current_price * 0.005

                        qty = cfg["lot_size"]
                        margin_required = margin_per_qty * qty
                        entry_value = entry_spread * qty
                        entry_side = "SELL" if signal == "SHORT" else "BUY"
                        legs = 2 if "spread" in execution_mode else 1
                        entry_fee, _ = calculate_statutory_charges(
                            charges_profile, entry_value, qty, entry_side, legs=legs
                        )

                        if state["current_capital"] >= (margin_required + entry_fee):
                            state["current_capital"] -= (margin_required + entry_fee)

                            # Structural stop
                            lookback = 5
                            if len(df) >= lookback:
                                candles = df.iloc[len(df) - lookback: len(df)]
                                structural_stop = float(candles["low"].min()) if signal == "LONG" else float(candles["high"].max())
                            else:
                                structural_stop = current_price - 100 if signal == "LONG" else current_price + 100

                            state["open_position"] = {
                                "type": signal,
                                "entry_spot": current_price,
                                "entry_spread": entry_spread,
                                "qty": qty,
                                "datetime": current_dt_str,
                                "entry_fee": entry_fee,
                                "structural_stop": structural_stop,
                                "margin_blocked": margin_required,
                            }
                            
                # Mark this candle as processed
                state["last_processed_candle"] = last_candle_time

            # Update live PnL and Metrics continuously
            effective = state["current_capital"]
            unrealized = 0.0
            if state["open_position"]:
                sd = current_price - state["open_position"]["entry_spot"]
                unrealized = (sd if state["open_position"]["type"] == "LONG" else -sd) * spread_delta * state["open_position"]["qty"]
                effective += state["open_position"]["margin_blocked"] + unrealized
                state["open_position"]["live_pnl"] = round(unrealized, 2)
            
            if effective > state["peak_capital"]:
                state["peak_capital"] = effective
            
            dd = ((state["peak_capital"] - effective) / state["peak_capital"] * 100.0) if state["peak_capital"] > 0 else 0.0
            if dd > state["max_drawdown"]:
                state["max_drawdown"] = dd

            # Recalculate metrics
            trades = state["trades"]
            total = len(trades)
            winners = sum(1 for t in trades if t["net_pnl"] > 0)
            losers = total - winners
            net_pnl = sum(t["net_pnl"] for t in trades) + unrealized
            win_rate = (winners / total * 100.0) if total > 0 else 0.0
            gross_profits = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
            gross_losses = sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0)
            pf = (gross_profits / abs(gross_losses)) if gross_losses != 0 else (gross_profits if gross_profits > 0 else 0.0)

            state["metrics"] = {
                "initial_capital": round(cfg["capital"], 2),
                "final_capital": round(effective, 2),
                "net_pnl": round(net_pnl, 2),
                "roi_pct": round(net_pnl / cfg["capital"] * 100, 2) if cfg["capital"] else 0.0,
                "total_trades": total,
                "win_rate_pct": round(win_rate, 2),
                "winning_trades": winners,
                "losing_trades": losers,
                "profit_factor": round(pf, 2),
                "max_drawdown_pct": round(state["max_drawdown"], 2),
                "avg_trade_pnl": round(net_pnl / total, 2) if total > 0 else 0.0,
                "profitable_days": sum(1 for v in state["daily_pnl"].values() if v > 0),
                "total_days": len(state["daily_pnl"]),
            }

    except Exception as e:
        logger.error(f"Paper trade engine error: {traceback.format_exc()}")
        with _engine_lock:
            _engine_state["error"] = str(e)
            
    finally:
        with _engine_lock:
            _engine_state["is_running"] = False
            _engine_state["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─── Public API ─────────────────────────────────────────────────────────────

def start_paper_trading() -> dict:
    """Start the live paper trade engine scheduler."""
    global _engine_state, _scheduler
    with _engine_lock:
        if _engine_state["is_active"]:
            return {"status": "already_running", "message": "Paper trading is already running"}

        _engine_state["is_active"] = True
        _engine_state["is_running"] = False
        _engine_state["started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _engine_state["stopped_at"] = None
        _engine_state["error"] = None
        # Do NOT reset "accounts" on every start to preserve open trades today!
        # Initialize missing accounts
        for cfg in PAPER_ACCOUNTS:
            acc_id = _account_id(cfg)
            if acc_id not in _engine_state["accounts"]:
                _engine_state["accounts"][acc_id] = _init_account_state(cfg)
            else:
                _engine_state["accounts"][acc_id]["status"] = "Live Monitoring"

        # Start the scheduler
        if not _scheduler.running:
            # Add job if it doesn't exist
            if not _scheduler.get_jobs():
                _scheduler.add_job(_run_live_tick, 'interval', seconds=30, id="paper_trade_engine")
            _scheduler.start()
        else:
            if not _scheduler.get_jobs():
                _scheduler.add_job(_run_live_tick, 'interval', seconds=30, id="paper_trade_engine")

    return {"status": "started", "message": "Live paper trading engine scheduled (30s interval)"}


def stop_paper_trading() -> dict:
    """Stop the paper trade engine."""
    global _engine_state, _scheduler
    with _engine_lock:
        _engine_state["is_active"] = False
        _engine_state["stopped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for acc in _engine_state["accounts"].values():
            acc["status"] = "Stopped"
        
        if _scheduler.running:
            try:
                _scheduler.remove_job("paper_trade_engine")
            except Exception:
                pass

    return {"status": "stopped", "message": "Live paper trading engine stopped"}


def get_paper_trade_status() -> dict:
    """Return current engine state + all account summaries."""
    with _engine_lock:
        accounts_list = []
        for acc_id, acc_data in _engine_state["accounts"].items():
            accounts_list.append({
                "account_id": acc_data.get("account_id", acc_id),
                "bot": acc_data.get("bot"),
                "exchange": acc_data.get("exchange"),
                "symbol": acc_data.get("symbol"),
                "execution_mode": acc_data.get("execution_mode"),
                "status": acc_data.get("status", "pending"),
                "error": acc_data.get("error"),
                "metrics": acc_data.get("metrics", {}),
                "trades": acc_data.get("trades", [])[-20:], # Only send last 20 for UI
                "has_open_position": acc_data.get("open_position") is not None,
                "open_position": acc_data.get("open_position")
            })

        # --- DYNAMIC INJECTION: BOT 4 LIVE SYNC ---
        import os, json
        bot4_state_file = os.path.join(os.getcwd(), "bot4_strategy_state.json")
        if os.path.exists(bot4_state_file):
            try:
                with open(bot4_state_file, "r") as f:
                    b4 = json.load(f)
                
                # Only inject if today's date matches (otherwise it's stale)
                if b4.get("date") == datetime.now().strftime("%Y-%m-%d"):
                    # Remove generic Bot 4 placeholders
                    accounts_list = [a for a in accounts_list if a.get("bot") != "bot4"]
                    
                    status = "Live Monitoring (External Daemon)"
                    if b4.get("aborted_for_day"):
                        status = f"Stopped ({b4.get('abort_reason', 'EOD')})"
                    elif "last_heartbeat" in b4:
                        if time.time() - b4["last_heartbeat"] > 10:
                            status = "CRITICAL: Daemon Disconnected"
                        
                    bot4_pnl = b4.get("realized_pnl", 0.0)
                    bot4_trades = []
                    bot4_open = None
                    has_open = False
                    
                    for leg_key in ["ce_leg", "pe_leg", "rec_ce_leg", "rec_pe_leg"]:
                        leg = b4.get(leg_key)
                        if leg:
                            if leg.get("is_open"):
                                has_open = True
                                bot4_open = {
                                    "type": "SHORT",
                                    "qty": leg.get("qty", 65),
                                    "entry_spot": leg.get("ref_spot", 0),
                                    "entry_spread": leg.get("entry_price", 0),
                                    "margin_blocked": 185000,
                                }
                            else:
                                bot4_trades.append({
                                    "direction": "SHORT_LEG",
                                    "qty": leg.get("qty", 65),
                                    "entry_price": round(leg.get("entry_price", 0), 2),
                                    "exit_price": 0.0,
                                    "net_pnl": 0.0,
                                    "exit_reason": "SL / Closed"
                                })
                                
                    accounts_list.append({
                        "account_id": "bot4_NSE_NIFTY_options_selling_live",
                        "bot": "bot4",
                        "exchange": "NSE",
                        "symbol": "NIFTY",
                        "execution_mode": "options_selling",
                        "status": status,
                        "error": None,
                        "metrics": _empty_metrics(185000.0),
                        "trades": bot4_trades,
                        "has_open_position": has_open,
                        "open_position": bot4_open
                    })
                    accounts_list[-1]["metrics"]["net_pnl"] = round(bot4_pnl, 2)
                    accounts_list[-1]["metrics"]["final_capital"] = 185000.0 + round(bot4_pnl, 2)
            except Exception as e:
                logger.error(f"Error injecting Bot 4 state: {e}")

        accounts_list.sort(
            key=lambda a: a.get("metrics", {}).get("net_pnl", 0),
            reverse=True
        )

        return {
            "status": "success",
            "is_active": _engine_state["is_active"],
            "is_running": _engine_state["is_running"],
            "started_at": _engine_state["started_at"],
            "stopped_at": _engine_state["stopped_at"],
            "last_run_at": _engine_state["last_run_at"],
            "error": _engine_state["error"],
            "total_accounts": len(accounts_list),
            "accounts": accounts_list,
        }
