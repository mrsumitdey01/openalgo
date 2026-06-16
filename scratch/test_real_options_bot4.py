import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

# Set up logging and data
def load_data(filepath):
    df = pd.read_csv(filepath)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Create lookup dict: (timestamp, strike, type) -> price
    lookup = {}
    for _, row in df.iterrows():
        lookup[(row['timestamp'], row['strike'], row['instrument_type'])] = row['close']
        
    return df, lookup

def run_real_backtest():
    filepath = "C:\\Users\\sumit\\.gemini\\antigravity\\worktrees\\OpenAlgo\\work-on-openalgo\\scratch\\real_options_10days.csv"
    df, lookup = load_data(filepath)
    
    # Extract unique timestamps and sort them
    timestamps = sorted(df['timestamp'].unique())
    
    days = sorted(list(set([t.date() for t in timestamps])))
    
    capital = 185000
    qty = 65
    
    pnl_history = []
    total_net_pnl = 0
    
    for day in days:
        print(f"Testing Day: {day}")
        day_times = [t for t in timestamps if t.date() == day]
        
        # Bot 4 State
        in_trade = False
        morning_aborted = False
        in_recovery = False
        
        active_legs = {} # strike_type -> {entry_price, qty}
        day_realized_pnl = 0
        
        # We need a proxy for spot price. We will estimate it from ATM options
        def get_spot(ts):
            ts_data = df[df['timestamp'] == ts]
            if len(ts_data) == 0: return None
            # Find the strike where CE and PE have closest prices
            strikes = ts_data['strike'].unique()
            min_diff = float('inf')
            best_spot = strikes[0]
            for s in strikes:
                ce = lookup.get((ts, s, 'CE'), 0)
                pe = lookup.get((ts, s, 'PE'), 0)
                if abs(ce - pe) < min_diff:
                    min_diff = abs(ce - pe)
                    best_spot = s
            return best_spot

        for ts in day_times:
            # 09:30 Entry
            if ts.hour == 9 and ts.minute == 30 and not in_trade and not morning_aborted:
                spot = get_spot(ts)
                atm_strike = round(spot / 50) * 50
                
                ce_price = lookup.get((ts, atm_strike, 'CE'))
                pe_price = lookup.get((ts, atm_strike, 'PE'))
                
                if ce_price and pe_price:
                    active_legs['CE'] = {'strike': atm_strike, 'entry': ce_price, 'type': 'CE'}
                    active_legs['PE'] = {'strike': atm_strike, 'entry': pe_price, 'type': 'PE'}
                    in_trade = True
                    morning_aborted = False
                    print(f"  [09:30] Sold Straddle at {atm_strike} | CE: {ce_price:.2f}, PE: {pe_price:.2f}")

            # 12:30 Recovery
            if ts.hour == 12 and ts.minute == 30 and not in_trade and morning_aborted and not in_recovery:
                spot = get_spot(ts)
                
                ce_strike = round((spot * 1.005) / 50) * 50
                pe_strike = round((spot * 0.995) / 50) * 50
                
                # Check if we have data for these strikes, if not pick closest
                strikes = df[df['timestamp'] == ts]['strike'].unique()
                if ce_strike not in strikes: ce_strike = min(strikes, key=lambda x: abs(x - ce_strike))
                if pe_strike not in strikes: pe_strike = min(strikes, key=lambda x: abs(x - pe_strike))
                
                ce_price = lookup.get((ts, ce_strike, 'CE'))
                pe_price = lookup.get((ts, pe_strike, 'PE'))
                
                if ce_price and pe_price:
                    active_legs['CE'] = {'strike': ce_strike, 'entry': ce_price, 'type': 'CE'}
                    active_legs['PE'] = {'strike': pe_strike, 'entry': pe_price, 'type': 'PE'}
                    in_trade = True
                    in_recovery = True
                    print(f"  [12:30] Arming Recovery Strangle CE: {ce_strike} @ {ce_price:.2f}, PE: {pe_strike} @ {pe_price:.2f}")

            # Stop Loss & MTM checks
            if in_trade:
                mtm = 0
                for leg_type, leg in list(active_legs.items()):
                    current_price = lookup.get((ts, leg['strike'], leg['type']))
                    if not current_price: continue
                    
                    # Short position PnL = Entry - Current
                    leg_pnl = (leg['entry'] - current_price) * qty
                    mtm += leg_pnl
                    
                    # We are using 1% spot SL in Bot4, but since we don't have accurate spot, 
                    # let's use a 30% premium spike SL for this mock real-data backtest
                    if current_price > leg['entry'] * 1.30:
                        day_realized_pnl += leg_pnl
                        print(f"  [{ts.strftime('%H:%M')}] SL Hit for {leg['type']} {leg['strike']}! Exit at {current_price:.2f} PnL: {leg_pnl:.2f}")
                        del active_legs[leg_type]
                        
                        # In Bot 4, if one leg hits SL, we close the other to lock decay, and we don't roll here for simplicity
                        for other_leg_type, other_leg in list(active_legs.items()):
                            other_price = lookup.get((ts, other_leg['strike'], other_leg['type']))
                            other_pnl = (other_leg['entry'] - other_price) * qty
                            day_realized_pnl += other_pnl
                            print(f"  [{ts.strftime('%H:%M')}] Squaring unhit leg {other_leg['type']} at {other_price:.2f} PnL: {other_pnl:.2f}")
                            del active_legs[other_leg_type]
                            
                        in_trade = False
                        if not in_recovery:
                            morning_aborted = True

                # Target / Max Loss
                if mtm + day_realized_pnl > 800:
                    print(f"  [{ts.strftime('%H:%M')}] Target Hit! PnL: {mtm + day_realized_pnl:.2f}")
                    day_realized_pnl += mtm
                    active_legs.clear()
                    in_trade = False
                elif mtm + day_realized_pnl < -3700:
                    print(f"  [{ts.strftime('%H:%M')}] Max Loss Breached! PnL: {mtm + day_realized_pnl:.2f}")
                    day_realized_pnl += mtm
                    active_legs.clear()
                    in_trade = False
                    morning_aborted = True
                    
            # Timed Exits
            if in_trade and in_recovery and ts.hour == 14 and ts.minute == 0:
                mtm = 0
                for leg_type, leg in active_legs.items():
                    current_price = lookup.get((ts, leg['strike'], leg['type']))
                    if current_price: mtm += (leg['entry'] - current_price) * qty
                if mtm < 0:
                    print(f"  [14:00] Recovery trade is negative, exiting to avoid Gamma. PnL: {mtm:.2f}")
                    day_realized_pnl += mtm
                    active_legs.clear()
                    in_trade = False
                    
            if in_trade and ts.hour == 15 and ts.minute == 15:
                mtm = 0
                for leg_type, leg in active_legs.items():
                    current_price = lookup.get((ts, leg['strike'], leg['type']))
                    if current_price: mtm += (leg['entry'] - current_price) * qty
                print(f"  [15:15] End of day square off. PnL: {mtm:.2f}")
                day_realized_pnl += mtm
                active_legs.clear()
                in_trade = False
                
        print(f"  => Day Net PnL: Rs.{day_realized_pnl:.2f}\n")
        total_net_pnl += day_realized_pnl
        pnl_history.append(day_realized_pnl)
        
    print("="*50)
    print("REAL OPTIONS 10-DAY BACKTEST RESULTS")
    print("="*50)
    print(f"Total Net PnL: Rs.{total_net_pnl:.2f}")
    win_days = sum(1 for p in pnl_history if p > 0)
    print(f"Win Rate: {(win_days/len(days))*100:.2f}% ({win_days} Wins / {len(days)-win_days} Losses)")
    print("="*50)

if __name__ == "__main__":
    run_real_backtest()
