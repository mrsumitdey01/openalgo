import duckdb

db_path = r"C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\db\historify.duckdb"

conn = duckdb.connect(db_path, read_only=True)

query = "SELECT COUNT(*) FROM market_data WHERE symbol = 'CRUDEOIL' AND exchange = 'MCX'"
print("CRUDEOIL MCX Count:", conn.execute(query).fetchone()[0])

query = "SELECT COUNT(*) FROM market_data WHERE symbol = 'CRUDEOIL' AND exchange = 'MCX_INDEX'"
print("CRUDEOIL MCX_INDEX Count:", conn.execute(query).fetchone()[0])

query = "SELECT DISTINCT interval FROM market_data LIMIT 10"
print("Intervals in DB:", conn.execute(query).fetchall())

conn.close()
