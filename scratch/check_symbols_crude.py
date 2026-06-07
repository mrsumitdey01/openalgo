import sqlite3
import re

conn = sqlite3.connect('db/openalgo.db')
c = conn.cursor()

try:
    c.execute("SELECT broker_symbol FROM chartink_symbol_mappings WHERE broker_symbol LIKE '%CRUDEOIL%' LIMIT 20")
    print(c.fetchall())
except:
    pass

try:
    c.execute("SELECT broker_symbol FROM strategy_symbol_mappings WHERE broker_symbol LIKE '%CRUDEOIL%' LIMIT 20")
    print(c.fetchall())
except:
    pass
