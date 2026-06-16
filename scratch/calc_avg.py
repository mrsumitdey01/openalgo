import json

with open('bot4_10yr_verified.json') as f:
    data = json.load(f)

trades = data['trades']
wins = [t['net_pnl'] for t in trades if t['net_pnl'] > 0]
losses = [t['net_pnl'] for t in trades if t['net_pnl'] <= 0]

avg_win = sum(wins) / len(wins) if wins else 0
avg_loss = sum(losses) / len(losses) if losses else 0
avg_pnl = data['metrics']['net_pnl'] / len(trades)

print(f"Average Profit per Win: Rs. {avg_win:.2f}")
print(f"Average Loss per Loss: Rs. {avg_loss:.2f}")
print(f"Average Net PnL per Trade: Rs. {avg_pnl:.2f}")
print(f"Risk/Reward Ratio: {abs(avg_loss) / avg_win if avg_win > 0 else 0:.2f} (Loss / Win)")
