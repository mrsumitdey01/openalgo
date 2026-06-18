import sqlite3
try:
    conn = sqlite3.connect('db/openalgo.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cursor.fetchall()]
    print("Tables:", tables)
    if 'bots' in tables:
        rows = cursor.execute("SELECT params FROM bots WHERE bot_id='bot4'").fetchall()
        print("Bot 4 params:")
        for r in rows:
            print(r[0])
except Exception as e:
    print("Error:", e)
