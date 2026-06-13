import duckdb
res = duckdb.connect('db/historify.duckdb').execute("SELECT DISTINCT symbol, exchange FROM market_data WHERE symbol='SENSEX'").fetchall()
print(res)
