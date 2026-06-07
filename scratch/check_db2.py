import sqlite3

conn = sqlite3.connect('db/openalgo.db')
c = conn.cursor()

c.execute('PRAGMA table_info(auth)')
print("Cols in auth:", [r[1] for r in c.fetchall()])
c.execute('SELECT * FROM auth')
print("Auth rows:", c.fetchall()[:2])

conn.close()
