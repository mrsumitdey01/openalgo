"""
===============================================================================
  INDICATOR_MATH.PY -- Pine Script -> Python Translation
  -------------------------------------------------------
  Hull BBI  : Hull Moving Average (Length 21) -- zero-lag momentum
  DTC Ribbon: 6-line Fibonacci EMA Cluster (8, 13, 21, 26, 34, 40)

  Synergy:
    The middle of the ribbon (EMA 21) mirrors the Hull BBI 21 lookback.
    Leading edges (8, 13) front-run momentum.
    Anchor (40) provides structural support.

  Pure numpy/pandas math with ZERO broker dependencies.
  These classes only add columns to DataFrames; they never place orders
  or interact with any external system.
===============================================================================
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from hullbot import config


# =============================================================================
#  HULL BBI  (Hull Moving Average)
# =============================================================================

class HullBBI:
    """Hull Moving Average -- zero-lag directional momentum indicator.

    Translated from Pine Script:
    -----------------------------------------------------------------------
        hullMA(src, length) =>
            wma1 = ta.wma(src, math.round(length / 2))
            wma2 = ta.wma(src, length)
            sqrtLength = math.round(math.sqrt(length))
            ta.wma(2 * wma1 - wma2, sqrtLength)

        hma = hullMA(close, 21)
        trend = hma > hma[1] ? color.blue : color.red
    -----------------------------------------------------------------------

    Mathematical steps (Length = 21):
        Step 1: WMA_half = WMA(Close, round(21/2))    = WMA(Close, 11)
        Step 2: WMA_full = WMA(Close, 21)
        Step 3: Diff     = 2 * WMA_half - WMA_full     (overshoot prediction)
        Step 4: HMA      = WMA(Diff, round(sqrt(21)))  = WMA(Diff, 5)

    The 2*WMA(n/2) - WMA(n) trick creates a "prediction" that overshoots
    the trend. The final WMA(sqrt(n)) smooths it back. This gives ~3x less
    lag than a standard EMA of the same period.

    WMA (Weighted Moving Average):
        WMA(x, n) = sum(x[i] * weight[i]) / sum(weights)
        Weights = [1, 2, 3, ..., n]  (most recent bar gets highest weight)
    """

    def __init__(self, length: int | None = None) -> None:
        self.length = length or config.HMA_LENGTH
        self.half_len = round(self.length / 2)          # 11 for length=21
        self.sqrt_len = round(math.sqrt(self.length))   # 5  for length=21

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute HMA and directional slope on a DataFrame.

        Adds these columns to df:
            'hma'          -- Hull Moving Average value
            'hma_prev'     -- HMA value from the previous candle
            'hma_bullish'  -- True if HMA is rising  (Blue/Green in Pine)
            'hma_bearish'  -- True if HMA is falling  (Red in Pine)

        Args:
            df: DataFrame with at least a 'close' column.

        Returns:
            Same DataFrame reference with new columns added in-place.
        """
        close = df["close"].astype(float)

        # Step 1: WMA of half-period (11)
        wma_half = self._wma(close, self.half_len)

        # Step 2: WMA of full period (21)
        wma_full = self._wma(close, self.length)

        # Step 3: Overshoot prediction
        # 2x the fast WMA minus the slow WMA extrapolates the trend
        diff = 2.0 * wma_half - wma_full

        # Step 4: Final smoothing with WMA(sqrt(n) = 5)
        hma = self._wma(diff, self.sqrt_len)

        df["hma"]          = hma
        df["hma_prev"]     = hma.shift(1)
        df["hma_bullish"]  = hma > hma.shift(1)
        df["hma_bearish"]  = hma < hma.shift(1)

        return df

    @staticmethod
    def _wma(series: pd.Series, period: int) -> pd.Series:
        """Weighted Moving Average using rolling window.

        Weights = [1, 2, 3, ..., period]
        Most recent value in the window gets the highest weight.

        Uses raw=True for numpy-level performance inside .apply().
        """
        weights = np.arange(1, period + 1, dtype=np.float64)
        weight_sum = weights.sum()

        return series.rolling(window=period, min_periods=period).apply(
            lambda x: np.dot(x, weights) / weight_sum,
            raw=True,
        )


# =============================================================================
#  DTC RIBBON  (6-EMA Fibonacci Cluster)
# =============================================================================

class DTCRibbon:
    """DTC Ribbon -- 6-line Fibonacci EMA cluster for trend confirmation.

    Translated from Pine Script (DTC v1.3.6):
    -----------------------------------------------------------------------
        // Fibonacci Cluster
        ma1 = ta.ema(close, 8)    // Fastest  (leading edge)
        ma2 = ta.ema(close, 13)   // Fast
        ma3 = ta.ema(close, 21)   // Mid (mirrors Hull BBI 21)
        ma4 = ta.ema(close, 26)   // Mid-slow
        ma5 = ta.ema(close, 34)   // Slow
        ma6 = ta.ema(close, 40)   // Anchor (structural support)

        // Strict alignment = all 6 EMAs in perfect order
        trendUp   = ma1>ma2 AND ma2>ma3 AND ma3>ma4 AND ma4>ma5 AND ma5>ma6
        trendDown = ma1<ma2 AND ma2<ma3 AND ma3<ma4 AND ma4<ma5 AND ma5<ma6

        // Fresh breakout = alignment JUST achieved on this candle
        buyCond  = trendUp  and not trendUp[1]
        sellCond = trendDown and not trendDown[1]
    -----------------------------------------------------------------------

    Why Fibonacci cluster (8, 13, 21, 26, 34, 40)?
        The previous 60-period anchor was too slow for 1-minute scalping,
        causing late entries and theta decay.  The tighter cluster:
        - Leading edges (8, 13) front-run momentum shifts
        - Mid (21) mirrors the Hull BBI lookback for synergy
        - Anchor (40) provides structural support without excessive lag

    Entry logic uses STRICT ALIGNMENT (not Close vs boundary):
        Long:  EMA8 > EMA13 > EMA21 > EMA26 > EMA34 > EMA40
        Short: EMA8 < EMA13 < EMA21 < EMA26 < EMA34 < EMA40

    EMA formula:
        EMA[t] = Close[t] * alpha + EMA[t-1] * (1 - alpha)
        alpha  = 2 / (period + 1)
    """

    def __init__(self, lengths: list[int] | None = None) -> None:
        self.lengths = lengths or list(config.EMA_LENGTHS)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute the 6-EMA Fibonacci ribbon with strict alignment.

        Adds these columns to df:
            'ema_8' ... 'ema_40'     -- Individual EMA values
            'ribbon_max'             -- Highest EMA at each bar
            'ribbon_min'             -- Lowest EMA at each bar
            'ribbon_bullish'         -- Strict ascending alignment
                                        (EMA8 > EMA13 > EMA21 > ... > EMA40)
            'ribbon_bearish'         -- Strict descending alignment
                                        (EMA8 < EMA13 < EMA21 < ... < EMA40)
            'ribbon_bullish_prev'    -- Previous candle's bullish alignment
            'ribbon_bearish_prev'    -- Previous candle's bearish alignment
            'ribbon_fresh_bull'      -- Alignment JUST achieved (buyCond)
            'ribbon_fresh_bear'      -- Alignment JUST achieved (sellCond)

        Args:
            df: DataFrame with at least a 'close' column.

        Returns:
            Same DataFrame reference with new columns added in-place.
        """
        close = df["close"].astype(float)

        # -- Calculate all 6 EMAs --
        ema_col_names: list[str] = []
        for length in self.lengths:
            col = f"ema_{length}"
            df[col] = close.ewm(span=length, adjust=False).mean()
            ema_col_names.append(col)

        # -- Ribbon boundaries --
        ema_matrix = df[ema_col_names]
        df["ribbon_max"] = ema_matrix.max(axis=1)
        df["ribbon_min"] = ema_matrix.min(axis=1)

        # -- Strict alignment (the core condition for signal qualification) --
        # Bullish: EMA8 > EMA13 > EMA21 > EMA26 > EMA34 > EMA40
        # Bearish: EMA8 < EMA13 < EMA21 < EMA26 < EMA34 < EMA40
        bullish = pd.Series(True, index=df.index)
        bearish = pd.Series(True, index=df.index)

        for i in range(len(ema_col_names) - 1):
            bullish = bullish & (df[ema_col_names[i]] > df[ema_col_names[i + 1]])
            bearish = bearish & (df[ema_col_names[i]] < df[ema_col_names[i + 1]])

        df["ribbon_bullish"] = bullish
        df["ribbon_bearish"] = bearish

        # -- Previous candle's alignment state (for fresh breakout detection) --
        df["ribbon_bullish_prev"] = bullish.shift(1).astype(bool).fillna(False)
        df["ribbon_bearish_prev"] = bearish.shift(1).astype(bool).fillna(False)

        # -- Fresh breakout: alignment JUST achieved on this candle --
        # buyCond  = trendUp  and not trendUp[1]
        # sellCond = trendDown and not trendDown[1]
        df["ribbon_fresh_bull"] = bullish & ~df["ribbon_bullish_prev"]
        df["ribbon_fresh_bear"] = bearish & ~df["ribbon_bearish_prev"]

        return df

class RSI:
    """Computes Wilder's Relative Strength Index (RSI)."""

    def __init__(self, length: int = 14) -> None:
        self.length = length

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adds 'rsi' column to DataFrame."""
        if len(df) < self.length:
            df["rsi"] = pd.NA
            return df

        delta = df["close"].diff()
        # Make two series: one for lower closes and one for higher closes
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        
        # Calculate the EWMA
        roll_up = up.ewm(com=self.length - 1, adjust=False).mean()
        roll_down = down.ewm(com=self.length - 1, adjust=False).mean()
        
        # Calculate the RSI
        rs = roll_up / roll_down
        df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

        return df

class ADX:
    """Computes Wilder's Average Directional Index (ADX)."""

    def __init__(self, length: int = 14) -> None:
        self.length = length

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < self.length:
            df["adx"] = pd.NA
            return df
            
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['close'].shift()).abs()
        tr3 = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        up_move = df['high'] - df['high'].shift()
        down_move = df['low'].shift() - df['low']
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        atr = tr.rolling(self.length).mean()
        plus_di = 100.0 * (pd.Series(plus_dm).rolling(self.length).mean() / atr)
        minus_di = 100.0 * (pd.Series(minus_dm).rolling(self.length).mean() / atr)

        dx = 100.0 * abs(plus_di - minus_di) / (plus_di + minus_di)
        df["adx"] = dx.rolling(self.length).mean()

        return df


