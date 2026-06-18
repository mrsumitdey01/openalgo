import json
jd = json.load(open('C:/Users/sumit/.gemini/antigravity/brain/9587d968-b1ce-47b3-8d2b-f7825a14166b/.system_generated/steps/16884/output.txt'))
trades = jd['data']['data']
for t in trades:
    if t['entryDate'].startswith('2026-03-04') or t['exitDate'].startswith('2026-03-04'):
        print(f"{t['legName']}: Entry {t['entryDate']} @ {t['entryPrice']}, Exit {t['exitDate']} @ {t['exitPrice']}, PnL: {t['pnl']}, Remark: {t['exitRemark']}")
