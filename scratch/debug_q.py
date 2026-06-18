import json, duckdb

with open('scratch/bot4_loss_days.json', 'r') as f:
    loss_days = json.load(f)

day = loss_days[0]
print(f"First loss day: {day}")

con = duckdb.connect('db/historify.duckdb', read_only=True)
q = f"""
SELECT * FROM market_data 
WHERE symbol='NIFTY' 
AND timestamp >= epoch(CAST('{day} 09:15:00' AS TIMESTAMP))
LIMIT 5
"""
print(con.execute(q).df())
