import sqlite3
import json
try:
    conn = sqlite3.connect('db/openalgo.db')
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(bot_config);")
    print("Columns:", cursor.fetchall())
    rows = cursor.execute("SELECT * FROM bot_config").fetchall()
    print("Configs:")
    for r in rows:
        print(r)
except Exception as e:
    print("Error:", e)
