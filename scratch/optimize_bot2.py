import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime
import itertools

# Add parent directory to path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database.historify_db import get_ohlcv

def get_data(exchange="MCX_INDEX", symbol="CRUDEOIL"):
    print(f"Fetching data for {symbol} ({exchange})...")
    
    # Get last 6 months
    import time
    end_ts = int(time.time())
    start_ts = end_ts - (180 * 24 * 60 * 60)
    
    df = get_ohlcv(symbol, exchange, "1m", start_timestamp=start_ts, end_timestamp=end_ts)
    if df is None or df.empty:
        print("No data found!")
        return None
    
    # The get_ohlcv already returns a DataFrame with 'timestamp' column or index
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('timestamp', inplace=True)
    elif not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, unit='s')
        
    df.sort_index(inplace=True)
    print(f"Loaded {len(df)} candles. From {df.index[0]} to {df.index[-1]}")
    return df

def calculate_metrics(trades, capital=100000):
    if not trades:
        return {"net_pnl": 0, "win_rate": 0, "max_dd": 0, "trades": 0, "profit_factor": 0}
    
    df_trades = pd.DataFrame(trades)
    winning = df_trades[df_trades['net_pnl'] > 0]
    losing = df_trades[df_trades['net_pnl'] <= 0]
    
    win_rate = len(winning) / len(trades) * 100
    gross_win = winning['net_pnl'].sum()
    gross_loss = abs(losing['net_pnl'].sum())
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf')
    
    # Drawdown
    df_trades['cum_pnl'] = df_trades['net_pnl'].cumsum()
    df_trades['equity'] = capital + df_trades['cum_pnl']
    df_trades['peak'] = df_trades['equity'].cummax()
    df_trades['dd'] = (df_trades['peak'] - df_trades['equity']) / df_trades['peak'] * 100
    max_dd = df_trades['dd'].max()
    
    return {
        "net_pnl": df_trades['net_pnl'].sum(),
        "win_rate": win_rate,
        "max_dd": max_dd,
        "trades": len(trades),
        "profit_factor": profit_factor
    }

def simulate_strategy(df, signals, sl_pts, tp_pts, unit_size=100):
    """
    signals: Series of 1 (Buy), -1 (Sell), 0 (Neutral)
    Simulates trades with fixed stop loss and take profit.
    For Crude Oil, tick size is 1. Brokerage approx Rs. 50 per trade total.
    """
    trades = []
    position = 0
    entry_price = 0
    entry_time = None
    
    # We iterate through the signals. To speed up, we can use vectorized approaches,
    # but for SL/TP path dependency, a compiled numba loop or simple iterrows is needed.
    # We will use simple array iteration for speed.
    
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    times = df.index
    sig_vals = signals.values
    
    for i in range(1, len(df)):
        if position == 0:
            if sig_vals[i] == 1:
                position = 1
                entry_price = closes[i]
                entry_time = times[i]
            elif sig_vals[i] == -1:
                position = -1
                entry_price = closes[i]
                entry_time = times[i]
        elif position == 1:
            # Check SL / TP
            if lows[i] <= entry_price - sl_pts:
                # Stopped out
                exit_price = entry_price - sl_pts
                gross = (exit_price - entry_price) * unit_size
                trades.append({"net_pnl": gross - 50, "type": "LONG"})
                position = 0
            elif highs[i] >= entry_price + tp_pts:
                # Take profit
                exit_price = entry_price + tp_pts
                gross = (exit_price - entry_price) * unit_size
                trades.append({"net_pnl": gross - 50, "type": "LONG"})
                position = 0
            elif sig_vals[i] == -1: # Reverse signal
                exit_price = closes[i]
                gross = (exit_price - entry_price) * unit_size
                trades.append({"net_pnl": gross - 50, "type": "LONG"})
                position = -1
                entry_price = closes[i]
                entry_time = times[i]
        elif position == -1:
            if highs[i] >= entry_price + sl_pts:
                exit_price = entry_price + sl_pts
                gross = (entry_price - exit_price) * unit_size
                trades.append({"net_pnl": gross - 50, "type": "SHORT"})
                position = 0
            elif lows[i] <= entry_price - tp_pts:
                exit_price = entry_price - tp_pts
                gross = (entry_price - exit_price) * unit_size
                trades.append({"net_pnl": gross - 50, "type": "SHORT"})
                position = 0
            elif sig_vals[i] == 1:
                exit_price = closes[i]
                gross = (entry_price - exit_price) * unit_size
                trades.append({"net_pnl": gross - 50, "type": "SHORT"})
                position = 1
                entry_price = closes[i]
                entry_time = times[i]
                
    return trades

def add_indicators(df):
    print("Calculating base indicators...")
    # EMA
    for period in [9, 13, 21, 34, 50, 200]:
        df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
        
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands
    df['sma_20'] = df['close'].rolling(window=20).mean()
    df['std_20'] = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['sma_20'] + (df['std_20'] * 2)
    df['bb_lower'] = df['sma_20'] - (df['std_20'] * 2)
    
    # Z-Score
    df['z_score'] = (df['close'] - df['sma_20']) / df['std_20']
    
    # ATR
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift())
    tr3 = abs(df['low'] - df['close'].shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['atr_14'] = tr.rolling(14).mean()
    
    # VWAP (Intraday)
    df['date'] = df.index.date
    df['typ_price'] = (df['high'] + df['low'] + df['close']) / 3
    df['vol_price'] = df['typ_price'] * df['volume']
    
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['cum_vol_price'] = df.groupby('date')['vol_price'].cumsum()
    df['vwap'] = df['cum_vol_price'] / df['cum_vol']
    
    # HMA
    def hma(series, period):
        half_length = int(period / 2)
        sqrt_length = int(np.sqrt(period))
        wmaf = series.ewm(span=half_length, adjust=False).mean()
        wmas = series.ewm(span=period, adjust=False).mean()
        diff = 2 * wmaf - wmas
        return diff.ewm(span=sqrt_length, adjust=False).mean()
        
    df['hma_9'] = hma(df['close'], 9)
    df['hma_21'] = hma(df['close'], 21)
    df['hma_50'] = hma(df['close'], 50)
    
    df.dropna(inplace=True)
    return df

def test_hma_atr_trend(df):
    """
    HMA + ATR Trend:
    Buy when HMA9 > HMA50.
    Sell when HMA9 < HMA50.
    Use ATR multiplier for Stop Loss to dynamically adjust to volatility.
    """
    print("\n--- Testing HMA + ATR Trend ---")
    best_metrics = None
    best_params = None
    
    for fast, slow, sl_atr_mult, tp_pts in itertools.product([9, 21], [21, 50], [1.5, 2.0, 3.0], [50, 100, 200]):
        if fast >= slow:
            continue
            
        signals = pd.Series(0, index=df.index)
        
        cross_up = (df[f'hma_{fast}'] > df[f'hma_{slow}']) & (df[f'hma_{fast}'].shift(1) <= df[f'hma_{slow}'].shift(1))
        cross_dn = (df[f'hma_{fast}'] < df[f'hma_{slow}']) & (df[f'hma_{fast}'].shift(1) >= df[f'hma_{slow}'].shift(1))
        
        signals[cross_up] = 1
        signals[cross_dn] = -1
        
        # We need a custom simulate that uses dynamic SL based on ATR
        trades = []
        position = 0
        entry_price = 0
        sl_price = 0
        
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        atrs = df['atr_14'].values
        sig_vals = signals.values
        
        for i in range(1, len(df)):
            if position == 0:
                if sig_vals[i] == 1:
                    position = 1
                    entry_price = closes[i]
                    sl_price = entry_price - (atrs[i] * sl_atr_mult)
                elif sig_vals[i] == -1:
                    position = -1
                    entry_price = closes[i]
                    sl_price = entry_price + (atrs[i] * sl_atr_mult)
            elif position == 1:
                # Update Trailing SL
                new_sl = closes[i] - (atrs[i] * sl_atr_mult)
                if new_sl > sl_price:
                    sl_price = new_sl
                    
                if lows[i] <= sl_price:
                    exit_price = sl_price
                    gross = (exit_price - entry_price) * 100
                    trades.append({"net_pnl": gross - 50, "type": "LONG"})
                    position = 0
                elif highs[i] >= entry_price + tp_pts:
                    exit_price = entry_price + tp_pts
                    gross = (exit_price - entry_price) * 100
                    trades.append({"net_pnl": gross - 50, "type": "LONG"})
                    position = 0
                elif sig_vals[i] == -1:
                    exit_price = closes[i]
                    gross = (exit_price - entry_price) * 100
                    trades.append({"net_pnl": gross - 50, "type": "LONG"})
                    position = -1
                    entry_price = closes[i]
                    sl_price = entry_price + (atrs[i] * sl_atr_mult)
            elif position == -1:
                new_sl = closes[i] + (atrs[i] * sl_atr_mult)
                if new_sl < sl_price:
                    sl_price = new_sl
                    
                if highs[i] >= sl_price:
                    exit_price = sl_price
                    gross = (entry_price - exit_price) * 100
                    trades.append({"net_pnl": gross - 50, "type": "SHORT"})
                    position = 0
                elif lows[i] <= entry_price - tp_pts:
                    exit_price = entry_price - tp_pts
                    gross = (entry_price - exit_price) * 100
                    trades.append({"net_pnl": gross - 50, "type": "SHORT"})
                    position = 0
                elif sig_vals[i] == 1:
                    exit_price = closes[i]
                    gross = (entry_price - exit_price) * 100
                    trades.append({"net_pnl": gross - 50, "type": "SHORT"})
                    position = 1
                    entry_price = closes[i]
                    sl_price = entry_price - (atrs[i] * sl_atr_mult)
                    
        metrics = calculate_metrics(trades)
        
        if metrics['trades'] > 50 and metrics['net_pnl'] > 0:
            score = metrics['win_rate'] / max(metrics['max_dd'], 1) * metrics['profit_factor']
            best_score = best_metrics['win_rate'] / max(best_metrics['max_dd'], 1) * best_metrics['profit_factor'] if best_metrics else 0
            
            if best_metrics is None or score > best_score:
                best_metrics = metrics
                best_params = {"fast": fast, "slow": slow, "sl_atr_mult": sl_atr_mult, "tp_pts": tp_pts}
                
    print(f"Best HMA Params: {best_params}")
    print(f"Best HMA Metrics: {best_metrics}")
    return best_metrics, best_params

def test_bb_reversion(df):
    """
    Mean Reversion with Trend Filter:
    Buy when price touches lower BB, RSI is oversold, AND price > EMA200 (Long-term Bullish).
    Sell when price touches upper BB, RSI is overbought, AND price < EMA200 (Long-term Bearish).
    """
    print("\n--- Testing Bollinger Band Mean Reversion ---")
    best_metrics = None
    best_params = None
    
    for rsi_os, rsi_ob, sl, tp in itertools.product([25, 30, 35], [65, 70, 75], [10, 15, 20], [20, 30, 50]):
        signals = pd.Series(0, index=df.index)
        
        # Bullish filter
        bull_trend = df['close'] > df['ema_200']
        buy_cond = bull_trend & (df['low'] <= df['bb_lower']) & (df['rsi_14'] <= rsi_os)
        
        # Bearish filter
        bear_trend = df['close'] < df['ema_200']
        sell_cond = bear_trend & (df['high'] >= df['bb_upper']) & (df['rsi_14'] >= rsi_ob)
        
        signals[buy_cond] = 1
        signals[sell_cond] = -1
        
        trades = simulate_strategy(df, signals, sl, tp)
        metrics = calculate_metrics(trades)
        
        if metrics['trades'] > 50 and metrics['net_pnl'] > 0:
            # Optimize for high win rate and extremely low drawdown
            score = (metrics['win_rate'] ** 2) / max(metrics['max_dd'], 0.1) * metrics['profit_factor']
            best_score = 0
            if best_metrics:
                best_score = (best_metrics['win_rate'] ** 2) / max(best_metrics['max_dd'], 0.1) * best_metrics['profit_factor']
                
            if best_metrics is None or score > best_score:
                best_metrics = metrics
                best_params = {"rsi_os": rsi_os, "rsi_ob": rsi_ob, "sl": sl, "tp": tp}
                
    print(f"Best BB Params: {best_params}")
    print(f"Best BB Metrics: {best_metrics}")
    return best_metrics, best_params

def test_ema_trend(df):
    """
    Trend Following:
    Buy when EMA 9 crosses above EMA 21 and price > EMA 200.
    Sell when EMA 9 crosses below EMA 21 and price < EMA 200.
    """
    print("\n--- Testing EMA Trend Following ---")
    best_metrics = None
    best_params = None
    
    for fast, slow, sl, tp in itertools.product([9, 13], [21, 34], [20, 30, 50], [40, 80, 150]):
        signals = pd.Series(0, index=df.index)
        
        ema_fast = df[f'ema_{fast}']
        ema_slow = df[f'ema_{slow}']
        ema_200 = df['ema_200']
        
        cross_up = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
        cross_dn = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))
        
        buy_cond = cross_up & (df['close'] > ema_200)
        sell_cond = cross_dn & (df['close'] < ema_200)
        
        signals[buy_cond] = 1
        signals[sell_cond] = -1
        
        trades = simulate_strategy(df, signals, sl, tp)
        metrics = calculate_metrics(trades)
        
        if metrics['trades'] > 50 and metrics['net_pnl'] > 0:
            if best_metrics is None or metrics['net_pnl'] > best_metrics['net_pnl']:
                best_metrics = metrics
                best_params = {"fast": fast, "slow": slow, "sl": sl, "tp": tp}
                
    print(f"Best EMA Params: {best_params}")
    print(f"Best EMA Metrics: {best_metrics}")
    return best_metrics, best_params

def test_zscore_momentum(df):
    """
    Z-Score Momentum Breakout:
    Buy when Z-Score > z_thresh (sudden violent upside momentum).
    Sell when Z-Score < -z_thresh (sudden violent downside momentum).
    """
    print("\n--- Testing Z-Score Momentum ---")
    best_metrics = None
    best_params = None
    
    for z_thresh, sl, tp in itertools.product([1.5, 2.0, 2.5], [10, 15, 20], [30, 50, 100]):
        signals = pd.Series(0, index=df.index)
        
        buy_cond = df['z_score'] > z_thresh
        sell_cond = df['z_score'] < -z_thresh
        
        signals[buy_cond] = 1
        signals[sell_cond] = -1
        
        trades = simulate_strategy(df, signals, sl, tp)
        metrics = calculate_metrics(trades)
        
        if metrics['trades'] > 50 and metrics['net_pnl'] > 0:
            if best_metrics is None or metrics['net_pnl'] > best_metrics['net_pnl']:
                best_metrics = metrics
                best_params = {"z_thresh": z_thresh, "sl": sl, "tp": tp}
                
    print(f"Best Z-Score Params: {best_params}")
    print(f"Best Z-Score Metrics: {best_metrics}")
    return best_metrics, best_params

def test_time_filtered_scalping(df):
    """
    Time-Filtered Scalping:
    Only trades during high volatility (US Session 18:00 - 22:00 IST).
    Uses strict RSI extremes to scalp small profits with tight stops.
    """
    print("\n--- Testing Time-Filtered Scalping ---")
    best_metrics = None
    best_params = None
    
    # Extract hour from timestamp
    df['hour'] = df.index.hour
    
    for rsi_os, rsi_ob, sl, tp in itertools.product([20, 25], [75, 80], [10, 15, 20], [10, 15, 20]):
        signals = pd.Series(0, index=df.index)
        
        # Only trade between 18:00 and 22:00
        time_cond = (df['hour'] >= 18) & (df['hour'] <= 22)
        
        buy_cond = time_cond & (df['rsi_14'] <= rsi_os) & (df['low'] <= df['bb_lower'])
        sell_cond = time_cond & (df['rsi_14'] >= rsi_ob) & (df['high'] >= df['bb_upper'])
        
        signals[buy_cond] = 1
        signals[sell_cond] = -1
        
        trades = simulate_strategy(df, signals, sl, tp)
        metrics = calculate_metrics(trades)
        
        if metrics['trades'] > 20 and metrics['net_pnl'] > 0:
            # We want High Win Rate and Low DD
            score = metrics['win_rate'] / max(metrics['max_dd'], 1) * metrics['profit_factor']
            best_score = best_metrics['win_rate'] / max(best_metrics['max_dd'], 1) * best_metrics['profit_factor'] if best_metrics else 0
            
            if best_metrics is None or score > best_score:
                best_metrics = metrics
                best_params = {"rsi_os": rsi_os, "rsi_ob": rsi_ob, "sl": sl, "tp": tp}
                
    print(f"Best Scalping Params: {best_params}")
    print(f"Best Scalping Metrics: {best_metrics}")
    return best_metrics, best_params

def test_vwap_pullback(df):
    """
    VWAP Pullback:
    Buy when price is in an uptrend (EMA9 > EMA34) and pulls back to touch VWAP, then closes above it.
    Sell when price is in downtrend (EMA9 < EMA34) and rallies to touch VWAP, then closes below it.
    """
    print("\n--- Testing VWAP Pullback ---")
    best_metrics = None
    best_params = None
    
    for sl, tp in itertools.product([15, 20, 25], [30, 45, 60]):
        signals = pd.Series(0, index=df.index)
        
        # Uptrend: Fast EMA > Slow EMA
        uptrend = df['ema_9'] > df['ema_34']
        # Pullback to VWAP: Low went below VWAP, but closed above
        pullback_up = (df['low'] <= df['vwap']) & (df['close'] > df['vwap'])
        
        # Downtrend: Fast EMA < Slow EMA
        downtrend = df['ema_9'] < df['ema_34']
        # Pullback to VWAP: High went above VWAP, but closed below
        pullback_dn = (df['high'] >= df['vwap']) & (df['close'] < df['vwap'])
        
        buy_cond = uptrend & pullback_up
        sell_cond = downtrend & pullback_dn
        
        signals[buy_cond] = 1
        signals[sell_cond] = -1
        
        trades = simulate_strategy(df, signals, sl, tp)
        metrics = calculate_metrics(trades)
        
        if metrics['trades'] > 50 and metrics['net_pnl'] > 0:
            score = metrics['win_rate'] / max(metrics['max_dd'], 1) * metrics['profit_factor']
            best_score = best_metrics['win_rate'] / max(best_metrics['max_dd'], 1) * best_metrics['profit_factor'] if best_metrics else 0
            
            if best_metrics is None or score > best_score:
                best_metrics = metrics
                best_params = {"sl": sl, "tp": tp}
                
    print(f"Best VWAP Params: {best_params}")
    print(f"Best VWAP Metrics: {best_metrics}")
    return best_metrics, best_params

if __name__ == "__main__":
    df = get_data()
    if df is not None:
        df = add_indicators(df)
        bb_m, bb_p = test_bb_reversion(df)
        ema_m, ema_p = test_ema_trend(df)
        z_m, z_p = test_zscore_momentum(df)
        sc_m, sc_p = test_time_filtered_scalping(df)
        hma_m, hma_p = test_hma_atr_trend(df)
        v_m, v_p = test_vwap_pullback(df)
