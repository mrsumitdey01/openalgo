import duckdb

DB_PATH = r"C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\db\historify.duckdb"
con = duckdb.connect(DB_PATH)

# Check average prices for 2018-01-01 to see if it's 10,000 (Nifty 50) or something else
rows = con.execute("SELECT date_trunc('day', to_timestamp(timestamp)) as d, AVG(close) FROM market_data WHERE symbol='NIFTY' AND timestamp BETWEEN 1514764800 AND 1517443200 GROUP BY d ORDER BY d LIMIT 10").fetchall()
for r in rows:
    print(r)

con.close()
