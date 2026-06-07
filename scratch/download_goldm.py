import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta
import pandas as pd

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.auth_db import db_session, Auth, safe_decrypt_token

with db_session() as session:
    auth_record = session.query(Auth).filter(Auth.broker == "fyers").first()
    if not auth_record:
        print("No auth record found for Fyers")
        exit(1)
        
    # The stored auth string is the JWT access token itself
    access_token = safe_decrypt_token(auth_record.auth)
    
client_id = "FFSTJBS5TJ-100"

symbol = "MCX:GOLDM26JULFUT" # Continuous future using an active contract as base

end_date = datetime.now()
start_date = end_date - timedelta(days=5*365)

print(f"Downloading from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")

all_data = []
current_end = end_date

while current_end > start_date:
    current_start = current_end - timedelta(days=90)
    if current_start < start_date:
        current_start = start_date
        
    url = f"https://api-t1.fyers.in/data/history"
    params = {
        "symbol": symbol,
        "resolution": "1",
        "date_format": "1",
        "range_from": current_start.strftime("%Y-%m-%d"),
        "range_to": current_end.strftime("%Y-%m-%d"),
        "cont_flag": "1"
    }
    
    headers = {
        "Authorization": f"{client_id}:{access_token}"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        if data.get("s") == "ok":
            candles = data.get("candles", [])
            print(f"Downloaded {len(candles)} candles from {current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}")
            all_data.extend(candles)
        else:
            print(f"Error for {current_start.strftime('%Y-%m-%d')}: {data}")
    except Exception as e:
        print(f"Exception: {e}")
        
    current_end = current_start - timedelta(days=1)
    time.sleep(0.5)

if all_data:
    df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
    df = df.sort_values('timestamp').drop_duplicates('timestamp')
    
    filename = "GOLDM_1min_5years.csv"
    df.to_csv(filename, index=False)
    print(f"Saved {len(df)} total rows to {filename}")
else:
    print("No data downloaded")
