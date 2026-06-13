"""
Read the CSV and do deep analysis to extract actionable insights.
"""
import pandas as pd

df = pd.read_csv('scratch/trade_log_3yr.csv')

print("=" * 70)
print("  DEEP PATTERN ANALYSIS — 3 Years, 716 Trades")
print("=" * 70)

print("\n--- PATTERN SUMMARY ---")
pat = df.groupby('pattern').agg(
    Count=('net_pnl', 'count'),
    Total_PnL=('net_pnl', 'sum'),
    Avg_PnL=('net_pnl', 'mean'),
    Avg_Range=('day_range_pct', 'mean'),
).sort_values('Total_PnL', ascending=False)
print(pat.to_string())

print("\n\n--- LOSS_CE_TREND DEEP DIVE ---")
trend = df[df['pattern'] == 'LOSS_CE_TREND'].copy()
print(f"Total count: {len(trend)}")
print(f"Total loss: Rs.{trend['net_pnl'].sum():,.0f}")
print(f"Avg loss: Rs.{trend['net_pnl'].mean():,.0f}")
print(f"Avg range on these days: {trend['day_range_pct'].mean():.2f}%")
print(f"Days where range > 0.8%: {(trend['day_range_pct'] > 0.8).sum()}")
print(f"Days where range 0.5-0.8%: {((trend['day_range_pct'] >= 0.5) & (trend['day_range_pct'] <= 0.8)).sum()}")
print(f"Days where range < 0.5%: {(trend['day_range_pct'] < 0.5).sum()}")

# CE SL hit time distribution on loss days
trend_with_sl = trend[trend['ce_sl_time'] != '-']
trend_with_sl = trend_with_sl.copy()
trend_with_sl['ce_sl_hour'] = trend_with_sl['ce_sl_time'].apply(lambda x: int(str(x)[:2]) if ':' in str(x) else -1)
print(f"\nCE SL Hit Time Distribution on Trend Loss Days:")
print(trend_with_sl['ce_sl_hour'].value_counts().sort_index().to_string())

print("\n\n--- LOSS_CE_TREND: Were These Profitable Before CE SL Hit? ---")
trend_with_peak = trend[trend['peak_mtm'] > 200]
print(f"Days that were profitable (peak>200) before going to loss: {len(trend_with_peak)}")
print(f"  -> These could have been saved by earlier exit or break-even lock")
print(f"  Avg peak MTM before going negative: Rs.{trend_with_peak['peak_mtm'].mean():,.0f}")
print(f"  Avg final loss: Rs.{trend_with_peak['net_pnl'].mean():,.0f}")

print("\n\n--- LOSS_CHARGES_ONLY DEEP DIVE ---")
flat = df[df['pattern'] == 'LOSS_CHARGES_ONLY'].copy()
print(f"Total count: {len(flat)}, Total lost: Rs.{flat['net_pnl'].sum():,.0f}")
print(f"Avg charges paid per flat day: Rs.{flat['charges'].mean():,.0f}")
print(f"DOW breakdown: {flat['dow'].value_counts().to_dict()}")
print(f"Year breakdown: {flat['year'].value_counts().sort_index().to_dict()}")
print(f"Avg range on flat days: {flat['day_range_pct'].mean():.2f}%")

# Key insight: flat days are almost ALL Wednesday (half qty). Others?
non_wed_flat = flat[flat['dow'] != 'Wed']
wed_flat = flat[flat['dow'] == 'Wed']
print(f"\nFlat Wed days: {len(wed_flat)} | Flat non-Wed days: {len(non_wed_flat)}")
if len(non_wed_flat) > 0:
    print(f"Non-Wed flat days loss: Rs.{non_wed_flat['net_pnl'].sum():,.0f}")
    print(f"Avg range on non-Wed flat days: {non_wed_flat['day_range_pct'].mean():.2f}%")

print("\n\n--- WINNING DAYS: What Makes Them Win? ---")
wins = df[df['net_pnl'] > 0].copy()
print(f"Total winning days: {len(wins)}")
print(f"Avg range: {wins['day_range_pct'].mean():.2f}%")
wins_with_sl = wins[wins['ce_sl_time'] != '-']
print(f"Wins where CE SL hit (leg stopped, other leg ran): {len(wins_with_sl)}")
print(f"  -> {len(wins_with_sl)/len(wins)*100:.1f}% of winning days had a leg hit SL")
print(f"  -> Avg win on days with leg stop: Rs.{wins_with_sl['net_pnl'].mean():,.0f}")
wins_no_sl = wins[wins['ce_sl_time'] == '-']
print(f"Wins where NO leg hit SL (pure theta decay): {len(wins_no_sl)}")
print(f"  -> Avg win on pure theta days: Rs.{wins_no_sl['net_pnl'].mean():,.0f}")

print("\n\n--- KEY HYPOTHESIS: Range-Based Gap Filter ---")
print("Currently: skip if opening GAP > 0.5% vs prev_close")
print("New idea: also skip if India VIX indicator (range estimate) is TOO LOW")
print("If previous-day range was < 0.4%, today might be flat too -> skip?")
print()
# Check if we could predict flat days from the previous day's range
# We don't have VIX data but we can proxy: if prev day range was narrow, today might be flat
df['prev_range'] = df['day_range_pct'].shift(1)
flat_days_prev_narrow = flat.merge(df[['date', 'prev_range']], on='date', how='left')
print(f"For flat loss days, avg prev-day range: {flat_days_prev_narrow['prev_range'].mean():.2f}%")
print(f"For winning days, avg prev-day range: {df[df['net_pnl']>0].merge(df[['date','prev_range']], on='date', how='left')['prev_range'].mean():.2f}%")

print("\n\n--- CRITICAL FINDING: Range Threshold Filter ---")
# What if we don't trade when range is predicted to be < 0.5%?
# Proxy: use previous day's actual range as predictor
# If prev_day_range < 0.4%, skip today
skip_threshold = 0.4
df_with_prev = df.merge(df[['date', 'day_range_pct']].rename(columns={'day_range_pct': 'prev_range', 'date': 'prev_date'}), 
                        left_on='date', right_on='prev_date', how='left')
# Simulate skipping days where prev range was below threshold
simulate = df.copy()
simulate['prev_range'] = simulate['day_range_pct'].shift(1).fillna(1.0)
skip_mask = simulate['prev_range'] < skip_threshold
skipped = simulate[skip_mask]
traded = simulate[~skip_mask]
print(f"If skip when prev-day range < {skip_threshold}%:")
print(f"  Days skipped: {skip_mask.sum()}")
print(f"  PnL of skipped days (missed): Rs.{skipped['net_pnl'].sum():,.0f}")
print(f"  PnL of remaining traded days: Rs.{traded['net_pnl'].sum():,.0f}")
print(f"  Win rate of remaining: {(traded['net_pnl']>0).sum()/len(traded)*100:.1f}%")
print(f"  Original total PnL: Rs.{df['net_pnl'].sum():,.0f}")

print("\n\n--- RESULT ---")
print(f"Original 3-year net PnL: Rs.{df['net_pnl'].sum():,.0f}")
print(f"Current win rate: {(df['net_pnl']>0).sum()/len(df)*100:.1f}%")
print(f"Baseline losses count: {(df['net_pnl']<0).sum()}")
