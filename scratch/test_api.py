import time
from openalgo import api
client = api('http://127.0.0.1:5000')
res = client.expiry(symbol='BANKNIFTY', exchange='NFO', instrumenttype='futures')
print(res)
