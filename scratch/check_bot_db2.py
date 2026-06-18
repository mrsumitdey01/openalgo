import sqlite3
for db in ['openalgo.db', 'historify.db', 'market_data.db', 'data/openalgo.db']:
    try:
        conn = sqlite3.connect(db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]
        print(f"--- {db} --- tables: {tables}")
        for t in tables:
            rows = cursor.execute(f"SELECT * FROM {t}").fetchall()
            print(f"Table {t} has {len(rows)} rows")
    except Exception as e:
        print(e)
