# Bot6c — DTC Intraday Stocks Execution Engine

## Overview
Bot6c is a production-grade intraday execution daemon for **NSE cash equities**, implementing the **DTC (Dynamic Trend Confirmation)** momentum strategy. It is a direct Python translation of the TradingView Pine Script 6-EMA ribbon indicator, built with strict **zero-repainting** and **zero-lookahead-bias** guarantees.

---

## Strategy Logic

### DTC Signal (6-EMA Ribbon)
The strategy uses **6 Exponential Moving Averages** with lengths: `8, 13, 21, 26, 34, 40`.

| Condition | Meaning | Action |
|---|---|---|
| `ema_8 > ema_13 > ema_21 > ema_26 > ema_34 > ema_40` | Strict bullish alignment (all EMAs fanned up) | **BUY signal** on the first such bar |
| `ema_8 < ema_13 < ema_21 < ema_26 < ema_34 < ema_40` | Strict bearish alignment (all EMAs fanned down) | **SELL signal** on the first such bar |
| Any mixed/tangled state | Neutral (grey ribbon) | **No trade** |

> **Anti-Lookahead**: Signals fire on bar `[i]`; execution happens at bar `[i+1]` open. The engine never touches the current unclosed candle.

---

## Risk Management

| Parameter | Value | Configurable |
|---|---|---|
| Allocated Capital | Rs. 50,000 | `config.py` |
| Leverage | 5x | `config.py` |
| Max Exposure | Rs. 2,50,000 | Derived |
| Position Qty | `floor(2,50,000 / entry_price)` | Automatic |
| Target | 0.4% from entry | `TARGET_PCT` in `config.py` |
| Initial SL | 0.3% from entry | `INITIAL_SL_PCT` in `config.py` |
| Trailing SL | 0.3% behind peak | `TRAIL_PCT` in `config.py` |

### Trailing Stop Logic
- **LONG**: As bar high rises, `trail_sl = max(trail_sl, bar_high * 0.997)` — never moves down.
- **SHORT**: As bar low falls, `trail_sl = min(trail_sl, bar_low * 1.003)` — never moves up.

### Exit Priority (same bar)
1. **Target Hit** (best case) → always fires first
2. **Trailing SL** → fires if target not hit
3. **Initial SL** → safety net (should rarely fire if trail works)

---

## Time Fences (IST)

| Fence | Time | Action |
|---|---|---|
| Market Start | 09:15 AM | No entries before this |
| Entry Cutoff | 14:45 PM | No **new** entries |
| Hard Square-Off | 15:15 PM | **All positions closed at market** |

---

## File Structure

```
bot6c/
├── config.py              # All configurable parameters
├── dtc_indicator.py       # DTC 6-EMA math engine (zero lookahead)
├── position_manager.py    # Sizing, SL, TP, trailing stop state machine
├── execution_engine.py    # Main event-driven bar loop
├── backtest_runner.py     # Backtesting harness + performance summary
├── bot6c_trades.log        # Execution log (auto-created on first run)
├── bot6c_tradelog.csv      # Trade CSV log (auto-created on first run)
└── tests/
    ├── test_dtc_indicator.py    # 12 tests: EMA, signals, zero lookahead
    ├── test_position_manager.py # 17 tests: sizing, SL, trail, exits
    └── test_time_fences.py      # 3 integration tests: time constraints
```

---

## How to Run

### 1. Demo Mode (Synthetic Data)
```bash
python backtest_runner.py --demo --symbol RELIANCE
```

### 2. With Real 1-min CSV Data
```bash
python backtest_runner.py --symbol RELIANCE --file reliance_1min.csv
```

**CSV Format:**
```csv
datetime,open,high,low,close,volume
2025-01-02 09:15:00,2950.00,2952.50,2948.00,2951.00,150000
```

### 3. Programmatic API
```python
from backtest_runner import run_backtest
import pandas as pd

df = pd.read_csv("reliance_1min.csv", parse_dates=["datetime"], index_col="datetime")
results = run_backtest("RELIANCE", df)
print(results["summary"])
```

---

## Running Tests
```bash
python -m pytest tests/ -v
```
Expected: **36/36 PASSED**, zero warnings.

---

## Tuning Parameters
Edit `config.py` to change strategy behavior:
```python
TARGET_PCT = 0.004      # 0.4% target — range: 0.003 to 0.005
INITIAL_SL_PCT = 0.003  # 0.3% hard stop
TRAIL_PCT = 0.003       # 0.3% trailing distance
CUTOFF_TIME = "14:45"   # Stop new entries at 14:45 IST
```

---

## Output Log Example
```
ENTRY FILL | RELIANCE LONG x99 @ 2527.57 | Time=12:01:00 | SL=2519.99 | TP=2537.68
TRADE CLOSED | RELIANCE LONG x99 | Entry=2527.57 Exit=2537.68 | PnL=+990.81 | Reason=TARGET_HIT
ENTRY FILL | RELIANCE SHORT x98 @ 2521.39 | Time=13:16:00 | SL=2528.95 | TP=2511.30
TRADE CLOSED | RELIANCE SHORT x98 | Entry=2521.39 Exit=2523.54 | PnL=-212.65 | Reason=TRAILING_SL
```
