import json
import duckdb
import pandas as pd
import numpy as np
import os
import math

class HullBBI:
    def __init__(self, length=21):
        self.length = length
        self.half_len = round(self.length / 2)
        self.sqrt_len = round(math.sqrt(self.length))

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        wma_half = self._wma(close, self.half_len)
        wma_full = self._wma(close, self.length)
        diff = 2.0 * wma_half - wma_full
        hma = self._wma(diff, self.sqrt_len)
        df["hma"] = hma
        df["hma_prev"] = hma.shift(1)
        df["hma_bullish"] = hma > hma.shift(1)
        df["hma_bearish"] = hma < hma.shift(1)
        return df

    @staticmethod
    def _wma(series: pd.Series, period: int) -> pd.Series:
        weights = np.arange(1, period + 1, dtype=np.float64)
        weight_sum = weights.sum()
        return series.rolling(window=period, min_periods=period).apply(
            lambda x: np.dot(x, weights) / weight_sum,
            raw=True,
        )

class DTCRibbon:
    def __init__(self, lengths=[8, 13, 21, 26, 34, 40]):
        self.lengths = lengths

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ema_col_names = []
        for length in self.lengths:
            col = f"ema_{length}"
            df[col] = close.ewm(span=length, adjust=False).mean()
            ema_col_names.append(col)

        ema_matrix = df[ema_col_names]
        df["ribbon_max"] = ema_matrix.max(axis=1)
        df["ribbon_min"] = ema_matrix.min(axis=1)

        bullish = pd.Series(True, index=df.index)
        bearish = pd.Series(True, index=df.index)
        for i in range(len(ema_col_names) - 1):
            bullish = bullish & (df[ema_col_names[i]] > df[ema_col_names[i + 1]])
            bearish = bearish & (df[ema_col_names[i]] < df[ema_col_names[i + 1]])

        df["ribbon_bullish"] = bullish
        df["ribbon_bearish"] = bearish
        return df

def run_recovery_test():
    with open('scratch/bot4_loss_days.json', 'r') as f:
        loss_days = json.load(f)
        
    print(f"Testing on {len(loss_days)} historically negative days.")
    
    con = duckdb.connect('db/historify.duckdb', read_only=True)
    
    hull_bbi = HullBBI()
    dtc_ribbon = DTCRibbon()
    
    wins = 0
    losses = 0
    total_net_pnl = 0.0
    
    for day in loss_days:
        query = f"""
        SELECT 
            timestamp, 
            open, high, low, close, volume 
        FROM market_data 
        WHERE symbol = 'NIFTY' 
          AND timestamp >= epoch(CAST('{day} 00:00:00' AS TIMESTAMP))
          AND timestamp <= epoch(CAST('{day} 23:59:59' AS TIMESTAMP))
        ORDER BY timestamp ASC
        """
        
        try:
            df = con.execute(query).df()
        except duckdb.Error as e:
            print(f"Error querying {day}: {e}")
            continue
            
        print(f"Day {day}: retrieved {len(df)} rows")
        if len(df) < 300:
            print(f"Skipping {day} due to short data")
            continue
            
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
        df = df.set_index('datetime')
        
        df['tr0'] = abs(df['high'] - df['low'])
        df['tr1'] = abs(df['high'] - df['close'].shift(1))
        df['tr2'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
        df['atr'] = df['tr'].rolling(14).mean()
        df['vol_ma'] = df['volume'].rolling(20).mean()
        
        df = hull_bbi.compute(df)
        df = dtc_ribbon.compute(df)
        
        position = None
        entry_price = 0.0
        pnl_pts = 0.0
        trades_taken = 0
        
        df['sma50'] = df['close'].rolling(50).mean()
        
        for idx, row in df.iterrows():
            t = idx.time()
            if t.hour < 10 or (t.hour == 10 and t.minute <= 30):
                continue
                
            if t.hour >= 15 and t.minute >= 15:
                if position == "LONG":
                    pnl_pts += (row['close'] - entry_price)
                elif position == "SHORT":
                    pnl_pts += (entry_price - row['close'])
                break
                
            close = float(row['close'])
            hma = float(row['hma'])
            hma_bullish = bool(row['hma_bullish'])
            hma_bearish = bool(row['hma_bearish'])
            ribbon_max = float(row['ribbon_max'])
            ribbon_min = float(row['ribbon_min'])
            
            atr = float(row['atr'])
            vol = float(row['volume'])
            vol_ma = float(row['vol_ma'])
            
            # Extreme Sure-Shot Filters
            is_long_cond = (close > hma) and hma_bullish and (close > ribbon_max) and (vol > 2.0 * vol_ma) and (atr > 6)
            is_short_cond = (close < hma) and hma_bearish and (close < ribbon_min) and (vol > 2.0 * vol_ma) and (atr > 6)
            
            if not position:
                if is_long_cond and trades_taken < 1: 
                    position = "LONG"
                    entry_price = close
                    trades_taken += 1
                elif is_short_cond and trades_taken < 1:
                    position = "SHORT"
                    entry_price = close
                    trades_taken += 1
            else:
                if position == "LONG":
                    if is_short_cond or (hma_bearish and (close < hma - 5.0)):
                        trade_pnl = (close - entry_price)
                        pnl_pts += trade_pnl
                        position = None
                elif position == "SHORT":
                    if is_long_cond or (hma_bullish and (close > hma + 5.0)):
                        trade_pnl = (entry_price - close)
                        pnl_pts += trade_pnl
                        position = None

        if pnl_pts > 0:
            wins += 1
        elif pnl_pts < 0:
            losses += 1
            
        total_net_pnl += pnl_pts
        
    print(f"Total Loss Days Recovered: {wins} Wins, {losses} Losses")
    print(f"Total Spot Points Recovered: {total_net_pnl:.2f}")
    if (wins+losses) > 0:
        print(f"Win Rate: {(wins/(wins+losses)*100):.2f}%")

if __name__ == '__main__':
    run_recovery_test()
