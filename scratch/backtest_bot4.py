import pandas as pd
import duckdb
from datetime import datetime, time, timedelta

DB_PATH = 'db/historify.duckdb'

def run_bot4_simulation(symbol, start_date, end_date):
    con = duckdb.connect(DB_PATH)
    
    # Check if table exists
    tables = con.execute("SHOW TABLES").df()
    if 'market_data' not in tables['name'].values:
        print("Table 'market_data' does not exist.")
        return
        
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
        print(f"No data for {symbol} between {start_date} and {end_date}")
        return
        
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
    df.set_index('datetime', inplace=True)
    
    # Group by date to iterate day by day
    grouped = df.groupby(df.index.date)
    
    capital = 800000.0
    initial_capital = capital
    wins = 0
    losses = 0
    max_drawdown = 0
    peak_capital = capital
    total_trades = 0
    
    for date, day_df in grouped:
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
            
            # Entry at 09:20
            if current_time.hour == 9 and current_time.minute == 20 and not entered:
                # We simulate selling Straddle at ATM
                # Since we don't have option prices, we synthesize option premiums using a rough approximation (e.g. 1% of spot each)
                # But actually, the paper trade engine uses spread_delta = 0.5.
                # Let's simulate Delta-neutral decay.
                # Options selling synthetic:
                ce_entry = current_price
                pe_entry = current_price
                
                ce_sl = current_price + (current_price * 0.005) # Spot moves 0.5% against CE
                pe_sl = current_price - (current_price * 0.005) # Spot moves 0.5% against PE
                
                ce_open = True
                pe_open = True
                entered = True
                total_trades += 2
                continue
                
            if entered:
                # Stop loss checks (Spot based simulation)
                if ce_open and current_price >= ce_sl:
                    ce_open = False
                    day_pnl -= (ce_sl - ce_entry) * 0.5 * 30 # loss
                
                if pe_open and current_price <= pe_sl:
                    pe_open = False
                    day_pnl -= (pe_entry - pe_sl) * 0.5 * 30 # loss
                
                # EOD Square off
                if current_time.hour == 15 and current_time.minute == 15:
                    if ce_open:
                        day_pnl += (ce_entry - current_price) * 0.5 * 30
                        ce_open = False
                    if pe_open:
                        day_pnl += (current_price - pe_entry) * 0.5 * 30
                        pe_open = False
                    break
                    
        # Apply strict 2% max MTM loss per day
        if day_pnl < -(initial_capital * 0.02):
            day_pnl = -(initial_capital * 0.02)
            
        capital += day_pnl
        if capital > peak_capital:
            peak_capital = capital
        drawdown = (peak_capital - capital) / peak_capital * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            
        if day_pnl > 0:
            wins += 1
        elif day_pnl < 0:
            losses += 1
            
    win_rate = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
    roi = ((capital - initial_capital) / initial_capital) * 100
    
    print(f"Results for {symbol} (1 Year):")
    print(f"Total Days Traded: {wins + losses}")
    print(f"Win Rate: {win_rate:.2f}% ({wins}W / {losses}L)")
    print(f"Total Return: {roi:.2f}%")
    print(f"Max Drawdown: {max_drawdown:.2f}%")
    print("-" * 40)

# Run for 1 year
end = datetime.now()
start = end - timedelta(days=365)

print("Starting backtest...")
run_bot4_simulation('BANKNIFTY', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
run_bot4_simulation('NIFTY', start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))
