import sqlite3
import json
try:
    conn = sqlite3.connect('db/openalgo.db')
    cursor = conn.cursor()
    rows = cursor.execute("SELECT * FROM bot_config WHERE bot_id='bot4'").fetchall()
    print("Bot 4 configs:")
    for r in rows:
        print(r)
except Exception as e:
    print("Error:", e)
