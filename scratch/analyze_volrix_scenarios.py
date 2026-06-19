import json

daywise_path = r'C:\Users\sumit\.gemini\antigravity\brain\9587d968-b1ce-47b3-8d2b-f7825a14166b\.system_generated\steps\20954\output.txt'
trades_path = r'C:\Users\sumit\.gemini\antigravity\brain\9587d968-b1ce-47b3-8d2b-f7825a14166b\.system_generated\steps\20966\output.txt'

try:
    with open(daywise_path, 'r', encoding='utf-8') as f:
        day_resp = json.load(f)['data']
        daywise_data = day_resp if isinstance(day_resp, list) else day_resp['data']
    with open(trades_path, 'r', encoding='utf-8') as f:
        tr_resp = json.load(f)['data']
        trades_data = tr_resp['data']['trades'] if 'data' in tr_resp and 'trades' in tr_resp['data'] else tr_resp['trades']
except Exception as e:
    print("Error loading data:", e)
    exit(1)

trades_by_date = {}
for t in trades_data:
    date_str = t['entryDate'].split('T')[0] if 'T' in t['entryDate'] else t['entryDate'].split()[0]
    if date_str not in trades_by_date:
        trades_by_date[date_str] = []
    trades_by_date[date_str].append(t)

scenarios = {}

daywise_data = [d for d in daywise_data if d['date'] in trades_by_date]

sorted_by_pnl = sorted(daywise_data, key=lambda x: x['pnl'], reverse=True)
scenarios['1. Best Positive Day'] = sorted_by_pnl[0]

sorted_by_loss = sorted(daywise_data, key=lambda x: x['pnl'])
scenarios['2. Max Loss Day'] = sorted_by_loss[0]

recovery_days = []
for d in daywise_data:
    d_str = d['date']
    d_trades = trades_by_date.get(d_str, [])
    if len(d_trades) >= 4 and d['pnl'] > 0:
        recovery_days.append(d)
if recovery_days:
    sorted_rec = sorted(recovery_days, key=lambda x: x['pnl'], reverse=True)
    scenarios['9. Recovery Strangle Victory'] = sorted_rec[0]

for name, d in scenarios.items():
    date_str = d['date']
    print(f"\n===== {name} ({date_str}) | PnL: {d['pnl']} =====")
    for t in sorted(trades_by_date.get(date_str, []), key=lambda x: x['entryTime']):
        print(f"Leg: {t.get('legName', 'N/A')} | Entry: {t['entryTime']} @ {t['entryPrice']} | Exit: {t['exitTime']} @ {t['exitPrice']} | Remark: {t.get('exitRemark', 'N/A')} | PnL: {t['pnl']}")

print("\n--- Additional Interesting Days (Fast Swings / Volatility) ---")
for i in range(1, min(6, len(sorted_by_loss))):
    date_str = sorted_by_loss[i]['date']
    d_trades = trades_by_date.get(date_str, [])
    print(f"\nBad Day {i} ({date_str}) PnL: {sorted_by_loss[i]['pnl']} | Trades: {len(d_trades)}")
    for t in sorted(d_trades, key=lambda x: x['entryTime']):
        print(f"Leg: {t.get('legName', 'N/A')} | Entry: {t['entryTime']} @ {t['entryPrice']} | Exit: {t['exitTime']} @ {t['exitPrice']} | Remark: {t.get('exitRemark', 'N/A')}")
