import pandas as pd
import numpy as np

dates = pd.date_range(start='2020-01-01', end='2024-01-01', freq='1min')
# Filter trading hours
df = pd.DataFrame(index=dates)
df = df.between_time('09:15', '15:29')
# Filter weekdays
df = df[df.index.dayofweek < 5]

print(f"Generating {len(df)} candles...")

# Random walk
np.random.seed(42)
returns = np.random.normal(0, 0.0005, size=len(df))
close_prices = 30000 * np.exp(np.cumsum(returns))

high_prices = close_prices * (1 + np.abs(np.random.normal(0, 0.0002, size=len(df))))
low_prices = close_prices * (1 - np.abs(np.random.normal(0, 0.0002, size=len(df))))
open_prices = (high_prices + low_prices) / 2

df['open'] = open_prices
df['high'] = high_prices
df['low'] = low_prices
df['close'] = close_prices
df['volume'] = np.random.randint(1000, 50000, size=len(df))
df['date'] = df.index

df.to_csv(r'C:\Users\sumit\.gemini\antigravity\worktrees\Algo\work-on-openalgo\data\mock_5yr.csv', index=False)
print("Generated mock dataset.")
