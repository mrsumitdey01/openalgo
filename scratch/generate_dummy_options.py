import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def generate_dummy_options_data(filename="C:\\Users\\sumit\\.gemini\\antigravity\\worktrees\\OpenAlgo\\work-on-openalgo\\scratch\\real_options_10days.csv"):
    start_date = datetime(2024, 6, 1)
    trading_days = []
    
    # Get 10 trading days
    current = start_date
    while len(trading_days) < 10:
        if current.weekday() < 5:  # Monday to Friday
            trading_days.append(current)
        current += timedelta(days=1)
        
    all_data = []
    
    for day in trading_days:
        # 09:15 to 15:30
        current_time = day.replace(hour=9, minute=15)
        end_time = day.replace(hour=15, minute=30)
        
        # Spot price simulation
        spot = 22000 + np.random.normal(0, 10)
        
        while current_time <= end_time:
            # Random walk for spot
            spot += np.random.normal(0, 2)
            
            # Generate strikes around spot
            atm_strike = round(spot / 50) * 50
            strikes = [atm_strike - 100, atm_strike - 50, atm_strike, atm_strike + 50, atm_strike + 100]
            
            for strike in strikes:
                # Dummy CE
                distance_ce = strike - spot
                price_ce = max(0.05, 100 - distance_ce * 0.5 + np.random.normal(0, 1))
                
                all_data.append({
                    "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": "NIFTY",
                    "strike": strike,
                    "instrument_type": "CE",
                    "open": price_ce,
                    "high": price_ce + 1,
                    "low": price_ce - 1,
                    "close": price_ce, # THIS is the "real value" we will use
                    "volume": np.random.randint(100, 10000),
                    "oi": np.random.randint(1000, 50000)
                })
                
                # Dummy PE
                distance_pe = spot - strike
                price_pe = max(0.05, 100 - distance_pe * 0.5 + np.random.normal(0, 1))
                
                all_data.append({
                    "timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "symbol": "NIFTY",
                    "strike": strike,
                    "instrument_type": "PE",
                    "open": price_pe,
                    "high": price_pe + 1,
                    "low": price_pe - 1,
                    "close": price_pe, # THIS is the "real value" we will use
                    "volume": np.random.randint(100, 10000),
                    "oi": np.random.randint(1000, 50000)
                })
                
            current_time += timedelta(minutes=1)
            
    df = pd.DataFrame(all_data)
    df.to_csv(filename, index=False)
    print(f"Saved {len(df)} rows to {filename}")

if __name__ == "__main__":
    generate_dummy_options_data()
