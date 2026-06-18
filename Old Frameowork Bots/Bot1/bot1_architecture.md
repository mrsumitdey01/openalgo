# 🤖 Bot 1: Hull BBI + DTC Ribbon Option Spread Bot

This document outlines the complete technical blueprint, mathematical foundation, configuration parameters, and execution lifecycle of **Bot 1** (the files in `src/hullbot/` without the `_v2` suffix).

---

## 📊 1. Indicator Math (`indicator_math.py`)

Bot 1 combines zero-lag directional momentum (**Hull BBI**) with trend-alignment confirmation (**DTC Ribbon**).

### A. Hull BBI (Hull Moving Average - HMA)
Translated directly from TradingView Pine Script:
* **Period:** 21 candles (1-minute)
* **Logic:** Extrapolates price direction by calculating a fast Weighted Moving Average (WMA) and a slow WMA to calculate overshoot, then smoothing it with a square-root period WMA:
  1. $\text{WMA}_{\text{half}} = \text{WMA}(\text{Close}, \text{round}(21 / 2)) = \text{WMA}(\text{Close}, 11)$
  2. $\text{WMA}_{\text{full}} = \text{WMA}(\text{Close}, 21)$
  3. $\text{Diff} = 2 \times \text{WMA}_{\text{half}} - \text{WMA}_{\text{full}}$
  4. $\text{HMA} = \text{WMA}(\text{Diff}, \text{round}(\sqrt{21})) = \text{WMA}(\text{Diff}, 5)$
* **Directional Output:**
  * **Bullish (Blue):** $\text{HMA} > \text{HMA}_{\text{prev}}$ (`hma_bullish`)
  * **Bearish (Red):** $\text{HMA} < \text{HMA}_{\text{prev}}$ (`hma_bearish`)

### B. DTC Ribbon (6-EMA Fibonacci Ribbon Cluster)
Combines 6 Exponential Moving Averages (EMAs) with Fibonacci periods to confirm macro structural alignment:
* **Lengths:** **8, 13, 21, 26, 34, 40**
* **Ribbon Boundaries:**
  * `ribbon_max` = Highest value of the 6 EMAs
  * `ribbon_min` = Lowest value of the 6 EMAs
* **Strict Alignment:**
  * **Bullish Alignment:** $\text{EMA}_8 > \text{EMA}_{13} > \text{EMA}_{21} > \text{EMA}_{26} > \text{EMA}_{34} > \text{EMA}_{40}$
  * **Bearish Alignment:** $\text{EMA}_8 < \text{EMA}_{13} < \text{EMA}_{21} < \text{EMA}_{26} < \text{EMA}_{34} < \text{EMA}_{40}$
* **Breakout Trigger:**
  * `ribbon_fresh_bull`: Bullish alignment is achieved on the *current* candle close, but was *not* true on the previous candle.
  * `ribbon_fresh_bear`: Bearish alignment is achieved on the *current* candle close, but was *not* true on the previous candle.

---

## 📈 2. Entry Plans (`signal_engine.py`)

Entries are strictly evaluated on **1-minute candle close** when there is no active position (flat). All 3 conditions must align simultaneously.

### 🟢 Bullish (LONG) Entry Conditions
1. **Price above Hull Line:** $\text{Candle Close} > \text{HMA}$
2. **Hull BBI is Rising:** HMA is Bullish (`hma_bullish` is True)
3. **Price above DTC Ribbon:** $\text{Candle Close} > \text{Ribbon Max}$ (Closed above all 6 Fibonacci EMAs)

### 🔴 Bearish (SHORT) Entry Conditions
1. **Price below Hull Line:** $\text{Candle Close} < \text{HMA}$
2. **Hull BBI is Falling:** HMA is Bearish (`hma_bearish` is True)
3. **Price below DTC Ribbon:** $\text{Candle Close} < \text{Ribbon Min}$ (Closed below all 6 Fibonacci EMAs)

---

## 📉 3. Exit Plans & Risk Management (`options_execution.py`)

Exits are built with asymmetry: exits are fast to protect capital, whereas entries are slow to prevent false breakouts.

### A. Opposite Signal Exit (Fast Exit)
Evaluated on **1-minute candle close**. If price crosses the HMA line and the Hull BBI shifts color, the position is closed:
* **LONG Exit:** $\text{HMA is Bearish (Red)} \text{ AND } \text{Candle Close} < (\text{HMA} - 5.0 \text{ points})$
* **SHORT Exit:** $\text{HMA is Bullish (Blue)} \text{ AND } \text{Candle Close} > (\text{HMA} + 5.0 \text{ points})$
*(Note: A 5-point buffer is applied to prevent micro-flickering exits).*

### B. Spot Structural Stop
Calculated **once** at the moment of entry based on spot price history:
* **LONG Stop Level:** Lowest Low of the last **5 candles** (`STRUCTURAL_STOP_LOOKBACK`) prior to entry.
* **SHORT Stop Level:** Highest High of the last **5 candles** prior to entry.
* **Breach Rule:** Evaluated on every candle close. If the Spot price closes below (for LONG) or above (for SHORT) this level, it triggers an immediate market exit.

### C. Spread stop loss (15%)
* Calculated by fetching the live Last Traded Price (LTP) of both options legs.
* **P&L formula:** $\text{Loss} = \text{Entry Premium Cost} - (\text{ATM LTP} - \text{OTM LTP})$.
* **Rule:** If the loss exceeds **15%** (`SPREAD_STOP_LOSS_PCT`) of the initial net premium paid, the spread is immediately market closed.

---

## ⚡ 4. Execution Lifecycle & Spreads Builder (`options_execution.py`)

### A. Strike Selection
* Spot price is rounded to the nearest strike interval (100 points for BankNifty / 50 points for Nifty).
  * Example: Spot 52,347 $\rightarrow$ ATM Strike 52,300.

### B. Spreads Structure
To limit max risk, Bot 1 never trades naked options. It enters hedged vertical spreads:
* **LONG Signal (Bull Call Spread):** Buy ATM CE + Sell OTM CE (ATM + 500 points).
* **SHORT Signal (Bear Put Spread):** Buy ATM PE + Sell OTM PE (ATM - 500 points).

### C. Limit Chasing Protocol
To avoid high slippage on market entries, a limit order modification loop is implemented:
1. **Initial Order:** Place BUY order for ATM leg at the current **Bid** (to get execution edge).
2. **Interval Modification:** If not filled after **1.5 seconds** (`BNF_CHASE_INTERVAL_SECS`), modify the price up by **₹0.15** (`BNF_CHASE_STEP_POINTS`).
3. **Slippage Cap:** Modification repeats up to **20 retries** (`BNF_CHASE_MAX_RETRIES`) or until the price exceeds **₹3.00** (`BNF_CHASE_MAX_SLIPPAGE_POINTS`) above the initial bid.
4. **Leg 2 execution:** Once the BUY leg fills, the SELL leg is placed and chased using the same logic.

### D. Leg Protection Protocol (Emergency Unwind)
* If the BUY leg fills successfully but the OTM SELL leg chasing fails (hits retries or slippage limit), the execution manager immediately fires an **emergency market order to sell/unwind the filled BUY leg**. This prevents the bot from holding a dangerous, unhedged naked option position.

### E. Time Gating (IST)
* **Market Stabilizing Warmup:** No entries before **09:30 AM** (`TRADE_START_HOUR:TRADE_START_MINUTE`).
* **Afternoon Block:** No new entries after **02:45 PM** (`NO_NEW_ENTRIES_HOUR:NO_NEW_ENTRIES_MINUTE`).
* **Hard EOD Exit:** If any trade is open at **03:15 PM** (`HARD_SQUARE_OFF_HOUR:HARD_SQUARE_OFF_MINUTE`), it is closed at market immediately.

---

## ⚙️ 5. Key Settings & Defaults (`config.py`)

| Parameter | Default Value | Purpose |
| :--- | :--- | :--- |
| `ACTIVE_BROKER` | `"FYERS"` (supports `"ZERODHA"`) | Broker integration target |
| `PAPER_MODE` | `True` | Live trade simulation block |
| `HMA_LENGTH` | `21` | Lookback for Hull BBI |
| `EMA_LENGTHS` | `[8, 13, 21, 26, 34, 40]` | DTC Ribbon EMA lookbacks |
| `OPTION_UNDERLYING` | `"BANKNIFTY"` | Target index |
| `LOT_SIZE` | `30` (BankNifty) / `65` (Nifty) | Contract lot size |
| `SPREAD_WIDTH` | `500` (BankNifty) / `200` (Nifty) | Spread spacing |
| `SPREAD_STOP_LOSS_PCT` | `0.15` (15%) | Max premium loss stop |
| `STRUCTURAL_STOP_LOOKBACK`| `5` (candles) | Spot low/high stop lookback |
| `BNF_CHASE_MAX_SLIPPAGE` | `3.0` | Max chasing points for BankNifty |
| `TRADE_START_TIME` | `09:30` | Earliest time for entries |
| `NO_NEW_ENTRIES_TIME` | `14:45` | Latest time for entries |
| `HARD_SQUARE_OFF_TIME` | `15:15` | EOD market square-off time |
