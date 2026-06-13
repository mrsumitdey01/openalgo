import pandas as pd
import duckdb
from datetime import datetime, time, timedelta
import numpy as np

DB_PATH = 'db/historify.duckdb'

def run_analysis(symbol, start_date, end_date):
    con = duckdb.connect(DB_PATH)
    
    query = f"""
    SELECT timestamp, open, high, low, close 
    FROM market_data 
    WHERE symbol='{symbol}' 
    AND timestamp >= epoch(CAST('{start_date} 00:00:00' AS TIMESTAMP))
    AND timestamp <= epoch(CAST('{end_date} 23:59:59' AS TIMESTAMP))
    ORDER BY timestamp ASC
    """
    
    df = con.execute(query).df()
    if df.empty:
        return None
        
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df.set_index('datetime', inplace=True)
    
    grouped = df.groupby(df.index.date)
    
    capital = 800000.0
    initial_capital = capital
    
    losing_days_data = []
    
    for date, day_df in grouped:
        if len(day_df) < 300: # Ignore incomplete days
            continue
            
        day_open = day_df.iloc[0]['open']
        day_high = day_df['high'].max()
        day_low = day_df['low'].min()
        day_close = day_df.iloc[-1]['close']
        
        # We need previous day close to check gaps, but since we are iterating, we can just grab the first candle's open 
        # and compare to the previous day_close. Let's track prev_day_close
        
        ce_entry = None
        pe_entry = None
        ce_sl = None
        pe_sl = None
        
        ce_open = False
        pe_open = False
        
        day_pnl = 0
        entered = False
        
        for idx, row in day_df.iterrows():
            current_time = idx.time()
            current_price = row['close']
            
            if current_time.hour == 9 and current_time.minute == 20 and not entered:
                ce_entry = current_price
                pe_entry = current_price
                
                ce_sl = current_price + (current_price * 0.005) # 0.5% spot move ~ 25% premium SL
                pe_sl = current_price - (current_price * 0.005)
                
                ce_open = True
                pe_open = True
                entered = True
                continue
                
            if entered:
                if ce_open and current_price >= ce_sl:
                    ce_open = False
                    day_pnl -= (ce_sl - ce_entry) * 0.5 * 30 # Synthesize 1 lot loss
                
                if pe_open and current_price <= pe_sl:
                    pe_open = False
                    day_pnl -= (pe_entry - pe_sl) * 0.5 * 30 
                
                if current_time.hour == 15 and current_time.minute == 15:
                    if ce_open:
                        day_pnl += (ce_entry - current_price) * 0.5 * 30
                        ce_open = False
                    if pe_open:
                        day_pnl += (current_price - pe_entry) * 0.5 * 30
                        pe_open = False
                    break
                    
        # Apply strict 2% max MTM loss per day
        hit_max_loss = False
        if day_pnl < -(initial_capital * 0.02):
            day_pnl = -(initial_capital * 0.02)
            hit_max_loss = True
            
        if day_pnl < 0:
            intraday_range_pct = (day_high - day_low) / day_open * 100
            trend_size_pct = abs(day_close - day_open) / day_open * 100
            
            losing_days_data.append({
                'date': date,
                'loss': day_pnl,
                'intraday_range_pct': intraday_range_pct,
                'trend_size_pct': trend_size_pct,
                'hit_max_loss': hit_max_loss
            })

    # Summary
    if not losing_days_data:
        return None
        
    losses_df = pd.DataFrame(losing_days_data)
    avg_loss = losses_df['loss'].mean()
    max_loss = losses_df['loss'].min()
    avg_range = losses_df['intraday_range_pct'].mean()
    avg_trend = losses_df['trend_size_pct'].mean()
    max_loss_days = losses_df['hit_max_loss'].sum()
    
    return {
        'symbol': symbol,
        'total_losing_days': len(losses_df),
        'avg_loss': avg_loss,
        'avg_intraday_range_pct': avg_range,
        'avg_trend_size_pct': avg_trend,
        'max_loss_hit_count': max_loss_days,
        'losses_df': losses_df
    }

end = datetime.now()
start = end - timedelta(days=365)
start_str = start.strftime('%Y-%m-%d')
end_str = end.strftime('%Y-%m-%d')

print("Analyzing losing trades...")
symbols = ['BANKNIFTY', 'NIFTY', 'SENSEX']

for sym in symbols:
    res = run_analysis(sym, start_str, end_str)
    if res:
        print(f"--- {sym} ---")
        print(f"Total Losing Days: {res['total_losing_days']}")
        print(f"Average Loss Amount: Rs.{res['avg_loss']:.2f}")
        print(f"Average Intraday Volatility (Range %): {res['avg_intraday_range_pct']:.2f}%")
        print(f"Average Directional Trend Size: {res['avg_trend_size_pct']:.2f}%")
        print(f"Times 2% Max Loss Triggered: {res['max_loss_hit_count']}")
        print(f"Pattern Insight: Losing days correlate with an intraday range of ~{res['avg_intraday_range_pct']:.2f}%")
        print("")
