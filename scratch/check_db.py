import sqlite3
import pandas as pd

conn = sqlite3.connect(r"C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\database\market_data.db")
query = "SELECT DISTINCT symbol, exchange, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM market_data GROUP BY symbol, exchange"
df = pd.read_sql_query(query, conn)
print("Symbols in DB:")
print(df)
conn.close()
