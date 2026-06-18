import sqlite3
for db in ['openalgo.db', 'historify.db']:
    try:
        conn = sqlite3.connect(db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]
        if 'bots' in tables:
            rows = cursor.execute("SELECT bot_id, params FROM bots WHERE bot_id='bot4'").fetchall()
            print(f"--- {db} ---")
            for r in rows:
                print(r)
    except Exception as e:
        print(e)
