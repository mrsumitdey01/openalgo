import json

daywise_path = r'C:\Users\sumit\.gemini\antigravity\brain\9587d968-b1ce-47b3-8d2b-f7825a14166b\.system_generated\steps\20954\output.txt'
trades_path = r'C:\Users\sumit\.gemini\antigravity\brain\9587d968-b1ce-47b3-8d2b-f7825a14166b\.system_generated\steps\20966\output.txt'

with open(daywise_path, 'r', encoding='utf-8') as f:
    day_resp = json.load(f)['data']
    daywise_data = day_resp if isinstance(day_resp, list) else day_resp['data']
with open(trades_path, 'r', encoding='utf-8') as f:
    tr_resp = json.load(f)['data']
    trades_data = tr_resp['data']['trades'] if 'data' in tr_resp and 'trades' in tr_resp['data'] else tr_resp['trades']

trades_by_date = {}
for t in trades_data:
    date_str = t['entryDate'].split('T')[0] if 'T' in t['entryDate'] else t['entryDate'].split()[0]
    if date_str not in trades_by_date:
        trades_by_date[date_str] = []
    trades_by_date[date_str].append(t)

scenarios = {}
traded_days = [d for d in daywise_data if d['date'] in trades_by_date]

# 1. Best Positive Day
scenarios['1. Positive/Theta Day'] = sorted(traded_days, key=lambda x: x['pnl'], reverse=True)[0]

# 2. Max Loss Day
scenarios['2. Max Loss Hit'] = sorted(traded_days, key=lambda x: x['pnl'])[0]

# 3. Recovery Win
for d in sorted(traded_days, key=lambda x: x['pnl'], reverse=True):
    t_d = trades_by_date[d['date']]
    if any("Recovery" in t.get('entryRemarks', '') for t in t_d) and d['pnl'] > 0:
        scenarios['9. Recovery Strangle Victory'] = d
        break

# 4. Low Volatility (EOD exit, no SL hit)
for d in sorted(traded_days, key=lambda x: x['pnl'], reverse=True):
    t_d = trades_by_date[d['date']]
    if len(t_d) == 2 and all("EOD" in t.get('exitRemarks', '') for t in t_d):
        scenarios['4. Low Volatility (EOD Exit)'] = d
        break

# 5. MTM Trailing Stop
for d in traded_days:
    t_d = trades_by_date[d['date']]
    if any("TRAILING" in t.get('exitRemarks', '') for t in t_d):
        scenarios['5. MTM Trailing Stop'] = d
        break

# 6. Gap Up/Down (No trades taken)
all_days = [d['date'] for d in daywise_data]
no_trade_days = [d for d in daywise_data if d['date'] not in trades_by_date]
if no_trade_days:
    scenarios['7. Gap Filter Abort'] = no_trade_days[0]

for name, d in scenarios.items():
    date_str = d['date']
    print(f"\n===== {name} ({date_str}) | PnL: {d['pnl']} =====")
    for t in sorted(trades_by_date.get(date_str, []), key=lambda x: x['entryTime']):
        print(f"Leg: {t.get('symbol')} | Entry: {t['entryTime']} @ {t['entryPrice']} ({t.get('entryRemarks')}) | Exit: {t['exitTime']} @ {t['exitPrice']} ({t.get('exitRemarks')}) | PnL: {t['pnl']}")

