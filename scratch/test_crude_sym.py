import requests
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database.auth_db import db_session, Auth, safe_decrypt_token

with db_session() as session:
    auth_record = session.query(Auth).filter(Auth.broker == "fyers").first()
    access_token = safe_decrypt_token(auth_record.auth)
    
client_id = "FFSTJBS5TJ-100"

symbols = ["MCX:CRUDEOIL1!", "MCX:CRUDEOIL-I", "MCX:CRUDEOIL24SEPFUT", "MCX:CRUDEOIL25MARFUT", "MCX:CRUDEOILM1!", "MCX:CRUDEOIL", "MCX:CRUDEOIL24NOVFUT", "MCX:CRUDEOIL26JULFUT", "MCX:CRUDEOIL25MAYFUT"]

for sym in symbols:
    url = f"https://api-t1.fyers.in/data/history"
    params = {
        "symbol": sym,
        "resolution": "1",
        "date_format": "1",
        "range_from": "2024-01-01",
        "range_to": "2024-01-10",
        "cont_flag": "1"
    }
    headers = {"Authorization": f"{client_id}:{access_token}"}
    resp = requests.get(url, params=params, headers=headers).json()
    if resp.get("s") == "ok":
        print(f"SUCCESS: {sym} -> {len(resp.get('candles', []))} candles")
    else:
        print(f"FAILED: {sym} -> {resp}")
