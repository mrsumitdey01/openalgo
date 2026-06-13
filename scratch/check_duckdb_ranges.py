import duckdb
from datetime import datetime

con = duckdb.connect('db/historify.duckdb')
res = con.execute("SELECT symbol, MIN(timestamp), MAX(timestamp), count(*) FROM market_data GROUP BY symbol").fetchall()

for row in res:
    sym = row[0]
    min_dt = datetime.fromtimestamp(row[1]).strftime('%Y-%m-%d')
    max_dt = datetime.fromtimestamp(row[2]).strftime('%Y-%m-%d')
    cnt = row[3]
    print(f"{sym}: {min_dt} to {max_dt} (count: {cnt})")
