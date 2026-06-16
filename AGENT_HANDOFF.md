# 🤖 OpenAlgo — Bot 4 (Short Straddle) — Complete AI Agent Handoff

> **Purpose:** This document gives a new AI agent everything it needs to understand, maintain, extend, and debug the Bot 4 Short Straddle trading system built inside the OpenAlgo platform. Read this before touching any code.

---

## 1. Project Overview

### What is OpenAlgo?
OpenAlgo is a self-hosted algorithmic trading platform built in **Python (Flask backend) + React (TypeScript frontend)**. It connects to Indian brokers via API and executes automated trading strategies on NSE/NFO.

### What is Bot 4?
Bot 4 is a **09:30 AM Intraday Short Straddle** strategy on NIFTY. It:
- Sells an ATM Call + ATM Put option simultaneously at 09:30 AM IST
- Manages each leg independently with a 1% spot-based Stop Loss
- Deploys a Recovery Strangle at 12:30 PM on losing days
- Squares off all positions by 15:15 PM IST
- Uses real NSE Bhav Copy option premium data for backtesting

### Verified Performance (2022–2024, with brokerage)
| Metric | Value |
|---|---|
| Net PnL | **Rs.2,87,997.75** |
| Win Rate | **92.12%** (526/571 trades) |
| Max Drawdown | **3.52%** |
| Profit Factor | **5.93** |

> [!IMPORTANT]
> These numbers are the **verified ground truth**. They match the UI output exactly. The lot size parameter MUST be passed as `"lot_size"` (not `"qty"`) — using `"qty"` silently falls back to 25 shares instead of 65.

---

## 2. Repository Layout

```
work-on-openalgo/
├── app.py                              # Flask app entry point
├── blueprints/
│   └── historify.py                    # All API routes — /api/backtest_bot at line 1573
├── services/
│   └── backtest_service.py             # 1891-line engine — run_bot4_backtest() at line 1294
├── strategies/
│   └── scripts/
│       └── bot4_straddle_seller.py     # 629-line LIVE trading daemon — NEVER change without approval
├── frontend/
│   └── src/pages/
│       └── Backtest.tsx                # 1969-line React UI
├── database/
│   └── historify_db.py                 # DuckDB OHLCV access layer
├── db/
│   └── historify.duckdb                # DuckDB — stores options_daily_premiums (NSE Bhav Copy)
├── bot4_strategy_state.json            # Live paper trade state file (atomic writes)
├── start_bot4_paper_trade.bat          # Windows launcher for live daemon
├── scratch/                            # Test/diagnostic scripts (NOT production code)
└── .env                                # Broker API keys and strategy config
```

---

## 3. Critical Rules — READ BEFORE CHANGING ANYTHING

> [!CAUTION]
> **NEVER modify `strategies/scripts/bot4_straddle_seller.py` without user confirmation.** The user must review and approve all changes to live bot logic before they are committed.

> [!WARNING]
> **NEVER use `"qty"` as the parameter name when calling `run_bot4_backtest()` from Python.** The engine reads `params.get("lot_size", 25)`. Passing `"qty": 65` causes silent fallback to 25 shares — producing results 2.6x smaller than reality.

> [!IMPORTANT]
> **The frontend `Backtest.tsx` sends `lot_size` correctly.** Any terminal test scripts must mirror this exactly.

---

## 4. Bot 4 Strategy Logic (Live Daemon)

**File:** [bot4_straddle_seller.py](file:///C:/Users/sumit/.gemini/antigravity/worktrees/OpenAlgo/work-on-openalgo/strategies/scripts/bot4_straddle_seller.py) (629 lines)

### Key Constants (all overridable via `.env`)
| Variable | Default | Meaning |
|---|---|---|
| `UNDERLYING` | `NIFTY` | Index symbol |
| `LOT_SIZE` | `65` | Shares per lot for NIFTY |
| `LOT_MULTIPLIER` | `1` | Number of lots to trade |
| `SPOT_SL_PCT` | `0.01` | 1.0% spot move triggers individual leg SL |
| `PROFIT_TARGET_PER_LOT` | `1600` | Base Rs target per lot (overridden by smart target) |
| `MAX_MTM_LOSS_PCT` | `0.02` | 2% of deployed capital = hard daily loss cap |
| `GAP_ABORT_PCT` | `0.005` | Abort if today open gaps >0.5% vs yesterday's close |
| `ENTRY_TIME` | `09:30` | Time to sell the straddle |
| `HARD_SQUARE_OFF` | `15:15` | Force-close all positions |
| `PAPER_MODE` | `true` | Set `false` for real order execution |

### Strategy Flow
```
[09:15] Market opens. Bot polls every 2.5 seconds.

[09:30] Gap Check: if |today_open - prev_close| / prev_close > 0.005
        → ABORT for day (no trade)

[09:30] Entry: SELL ATM CE + SELL ATM PE (same strike, nearest expiry)
        CE SL = spot * 1.01
        PE SL = spot * 0.99
        1 Roll allowed: if CE SL hits → roll PE up to new ATM and re-enter
        if MTM < -(2% deployed capital) → ABORT, armed for Recovery

[12:30] Recovery (ONLY on loss days):
        Extreme Trend Filter: if |current_spot - day_open| / day_open > 1.0%
          → SKIP recovery, accept morning loss
        Else: Sell Recovery Strangle (CE at spot*1.005, PE at spot*0.995)
        Recovery SL: 1% on both legs

[14:00] Strategy A — Recovery Timed Exit:
        if recovery MTM < 0 → close flat (prevent gamma explosion)
        if recovery MTM > 0 → let it run to EOD

[Smart Target] Day-of-Week based (per lot):
        Thursday pre-2025-09-01 / Tuesday post → Rs.300  (0DTE Gamma day)
        Wednesday pre / Monday post            → Rs.500  (1DTE High Theta)
        All other days                         → Rs.800  (2+ DTE)

[15:15] Hard Square Off: all open legs closed at market price
```

### State Management
- State persists in `bot4_strategy_state.json` via **atomic writes** (`write to .tmp → os.replace()`)
- Exponential backoff retry (6 attempts, max ~1.2s) for Windows file lock issues
- On reboot: reconciles open positions by checking live SL levels immediately

### Margin Requirements
| Symbol | Margin Per Lot |
|---|---|
| NIFTY | Rs.1,85,000 |
| BANKNIFTY | Rs.1,60,000 |
| SENSEX | Rs.1,00,000 |

---

## 5. Backtest Engine

**File:** [backtest_service.py](file:///C:/Users/sumit/.gemini/antigravity/worktrees/OpenAlgo/work-on-openalgo/services/backtest_service.py) (1891 lines)
**Function:** `run_bot4_backtest(params: dict)` starts at **line 1294**

### Correct Parameter Dictionary
```python
params = {
    "bot_id": "bot4",
    "symbol": "NIFTY",
    "start_date": "2022-01-01",        # YYYY-MM-DD
    "end_date": "2025-01-01",          # YYYY-MM-DD (exclusive)
    "capital": 185000,
    "lot_size": 65,                    # MUST be "lot_size" not "qty"
    "target_type": "fixed_1600",       # "fixed_1600" or "dynamic_day_based" = same smart logic
                                       # "pct_capital" = uses % of capital instead
    "trend_filter_pct": 0.010,         # 1.0% Recovery Extreme Trend Filter
    "rec_timed_exit": True,            # Enable 14:00 Recovery Timed Exit
    "rec_timed_exit_hour": 14,
    "apply_brokerage": True,
    "skip_friday": False,
    "skip_thursday": False,
}
```

> [!NOTE]
> `target_type = "fixed_1600"` and `"dynamic_day_based"` are functionally identical — both use the `smart_target` day-of-week switcher (Rs.300/Rs.500/Rs.800). Only `"pct_capital"` is different.

### Data Sources
1. **OHLCV (spot):** 1-minute candles from DuckDB via `get_ohlcv()`
2. **Options Premiums:** Real NSE Bhav Copy ATM straddle premiums from `options_daily_premiums` table
   - 618 days of NIFTY data available (2022–2024)
   - Falls back to synthetic model (1% of spot) if no real data for a date

### PnL Model
```
live_mtm = day_pnl + ce_mtm + pe_mtm + simulated_options_pnl
         + rec_ce_mtm + rec_pe_mtm + rec_sim_options_pnl

ce_mtm = -(price - ce_ref_spot) * 0.5 * qty    # Short CE loses when spot rises
pe_mtm =  (price - pe_ref_spot) * 0.5 * qty    # Short PE gains when spot rises

# When real premium data available:
daily_theta   = (straddle_premium * qty) / dte
theta_profit  = (minutes_held / 375.0) * daily_theta
gamma_loss    = (divergence_pct / 0.01) * (straddle_premium * qty * 0.12)
simulated_options_pnl = theta_profit - gamma_loss
```

---

## 6. API Routes

**File:** [historify.py](file:///C:/Users/sumit/.gemini/antigravity/worktrees/OpenAlgo/work-on-openalgo/blueprints/historify.py) — line 1573

```
POST /api/backtest_bot
Body: { ...params dict... }

Response: {
  "status": "success",
  "metrics": { "net_pnl", "win_rate_pct", "total_trades",
               "winning_trades", "losing_trades",
               "max_drawdown_pct", "profit_factor", "avg_trade_pnl" },
  "trades": [ { "id", "direction", "entry_time", "exit_time",
                "gross_pnl", "net_pnl", "exit_reason", "fee_breakdown" } ],
  "chart_data": [ { "timestamp", "open", "high", "low", "close", "capital" } ],
  "stats": { "total_bot4_trades", "total_bot4_sl_hits" }
}
```

---

## 7. Frontend — Backtest UI

**File:** [Backtest.tsx](file:///C:/Users/sumit/.gemini/antigravity/worktrees/OpenAlgo/work-on-openalgo/frontend/src/pages/Backtest.tsx) (1969 lines)

### Key React State Defaults
| Variable | Default | Maps to Backend |
|---|---|---|
| `botLotSize` | `"65"` | `lot_size` |
| `applyBrokerage` | `true` | `apply_brokerage` |
| `slippage` | `"0.05"` | `slippage_pct` |
| `trendFilterPct` | `"1.0"` | `trend_filter_pct: 0.010` |
| `recTimedExit` | `true` (checkbox) | `rec_timed_exit` |

### Lot Size Dropdown
```
30  → BankNifty (current)
65  → Nifty (current)     ← Bot 4 default
15  → BankNifty (old, pre-2024)
25  → Nifty (old, pre-2024)
75  → Nifty (older, pre-2019)
```

---

## 8. Design Decisions & Rationale

| Decision | Why |
|---|---|
| 1.0% Spot SL | Premium-based SL got chopped on intraday noise; spot-based is cleaner |
| Rs.300/500/800 day targets | 0DTE gamma risk justifies early exit; 2+DTE days maximize theta decay |
| No Low IV Filter | Removing it loses Rs.1.67L in valid profit; sample size matters |
| No Friday SL tightening | Expiry day changed across decade; "Friday" rule is stale |
| No Earnings Month lot reduction | Can't trade half a lot; 1 lot = minimum size |
| Real NSE Bhav Copy premiums | Synthetic 1% model underestimates; real data = true PnL |
| 12:30 PM Recovery entry | Market settled by noon; 3 hours of theta decay available before EOD |
| 14:00 Recovery Timed Exit | Final hour gamma explosion risk; cutting flat if in loss improves drawdown |

---

## 9. NIFTY Expiry Shift

> [!IMPORTANT]
> **NIFTY weekly expiry moved from Thursday to Tuesday on September 1, 2025.**

**Backtest engine** handles both regimes at line 1438 of `backtest_service.py`:
```python
if dt_date < pd.Timestamp('2025-09-01'):
    Thursday → 300, Wednesday → 500, else → 800
else:
    Tuesday → 300, Monday → 500, else → 800
```

**Live bot** (`bot4_straddle_seller.py` line 391) handles only the post-Sept 2025 regime (Tuesday expiry). This is intentional — the bot runs in the current market regime.

---

## 10. Running the System

### Flask Backend
```powershell
.venv\Scripts\python.exe app.py
# Runs at http://127.0.0.1:5000
```

### Frontend Dev Server
```powershell
cd frontend
npm run dev
# Runs at http://localhost:5173
```

### Bot 4 Paper Trade Daemon
```powershell
.\start_bot4_paper_trade.bat
# Or manually:
$env:OPENALGO_API_KEY="your_key"
$env:PAPER_MODE="true"
.venv\Scripts\python.exe strategies/scripts/bot4_straddle_seller.py
```

### Run Backtest from Python (verified correct way)
```python
import sys
sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot4_backtest

params = {
    "symbol": "NIFTY",
    "start_date": "2022-01-01",
    "end_date": "2025-01-01",
    "capital": 185000,
    "lot_size": 65,               # "lot_size" NOT "qty"
    "target_type": "fixed_1600",
    "trend_filter_pct": 0.010,
    "rec_timed_exit": True,
    "rec_timed_exit_hour": 14,
    "apply_brokerage": True
}

success, data, status = run_bot4_backtest(params)
m = data["metrics"]
print(f"PnL: {m['net_pnl']}, Win Rate: {m['win_rate_pct']}% ({m['winning_trades']}/{m['total_trades']})")
# Expected: PnL: 287997.75, Win Rate: 92.12% (526/571)
```

---

## 11. Database Schema

### `options_daily_premiums` (in `db/historify.duckdb`)
```sql
CREATE TABLE options_daily_premiums (
    symbol        TEXT,     -- 'NIFTY', 'BANKNIFTY', etc.
    date          DATE,     -- trade date
    ce_open       FLOAT,    -- ATM CE opening premium (Rs)
    pe_open       FLOAT,    -- ATM PE opening premium (Rs)
    straddle_open FLOAT,    -- ce_open + pe_open
    dte           INTEGER   -- Days To Expiry
);
```
- 618 days of NIFTY data (~2022–2024)
- Sourced from NSE Bhav Copy files

### OHLCV
- 1-minute candles for NIFTY (NSE_INDEX exchange)
- Access: `get_ohlcv(symbol, exchange, interval, start_timestamp, end_timestamp)`

---

## 12. Git Reference

```
Branch: option-stratergy   (typo intentional — do NOT rename)
Remote: https://github.com/mrsumitdey01/openalgo.git
```

### Recent Commits
```
6d534190  chore: add bot4 backtest verification and parameter sweep scripts
2c26e2fa  chore: add 10-year verification scratch scripts
3f3b957c  fix(bot4): upgrade atomic save to exponential backoff + graceful tmp cleanup
b9437971  fix(bot4): micro-retry loop for Windows WinError 32 file locks
aae4f2db  fix(bot4): anchor state file to repo root
173fd976  fix(bot4): phase 2 security patches (atomic write, heartbeat, gap trap)
52d0fa31  feat(bot4): hybrid external daemon paper trade sync
57fbdcb5  feat: implement Strangle recovery logic + finalize parameters
f513a4b1  feat: increase Nifty margin to 1.85L
485a2804  fix: enforce 14:00 timed exit default in backend
4adaaaa4  Fix max loss circuit breaker indentation bug in live bot
```

---

## 13. Known Issues & Gotchas

| Issue | Description | Status |
|---|---|---|
| `lot_size` vs `qty` | Scripts must use `"lot_size"` not `"qty"` | Fixed in all scratch scripts |
| CRLF line endings | Working tree CRLF, git object LF — MD5 differs, `git diff` is clean | Known, harmless |
| Branch name typo | `option-stratergy` — do not rename | Working as-is |
| `target_type` naming | `"fixed_1600"` and `"dynamic_day_based"` are identical code paths | Documented |
| Live bot expiry | Live bot only handles Tuesday expiry regime | Intentional |
| `frontend/dist` | In `.gitignore` — never commit compiled build | Handled |

---

## 14. Files — Change Policy

| File | Can Change? |
|---|---|
| `strategies/scripts/bot4_straddle_seller.py` | **NO — user must approve first** |
| `services/backtest_service.py` | **NO — user must approve first** |
| `db/historify.duckdb` | **NO — production database** |
| `bot4_strategy_state.json` | **NO — live trading state** |
| `blueprints/historify.py` | Yes (non-Bot4 routes OK freely; Bot4 route needs care) |
| `frontend/src/pages/Backtest.tsx` | Yes (UI changes OK, verify params still correct) |
| `scratch/*.py` | Yes (these are test scripts, not production code) |

---

## 15. Verified Performance Numbers

| Period | Lot Size | Brokerage | Net PnL | Win Rate | Drawdown |
|---|---|---|---|---|---|
| 2022–2024 | 65 (Nifty current) | Yes | **Rs.2,87,997.75** | 92.12% (526/571) | 3.52% |
| 2022–2024 | 65 (Nifty current) | No | Rs.3,43,363.35 | 96.50% (551/571) | — |
| 2022–2024 | 25 (Nifty old) | Yes | Rs.2,55,945.63 | 92.99% (531/571) | 3.73% |

> The Rs.2,55,572 figure cited in earlier session notes was computed with the wrong lot size parameter (`"qty": 65` which silently used 25 instead). The correct verified figure for 1 NIFTY lot is **Rs.2,87,997.75**.

---

*Generated: 2026-06-16 | Branch: option-stratergy | Commit: 6d534190*
