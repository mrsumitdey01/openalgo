import sys
sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot4_backtest
import json

params = {
    'strategy': 'bot4_straddle_seller',
    'symbol': 'NIFTY',
    'start_date': '2022-01-01',
    'end_date': '2025-01-01',
    'capital': 185000,
    'lot_size': 65,  # FIXED: properly use lot_size as UI does
    'entry_time': '09:30',
    'exit_time': '15:15',
    'sl_pct': 0.01,
    'max_loss_pct': 0.02,
    'target_type': 'fixed_1600',  # FIXED: use the actual UI default
    'gap_pct_abort': 0.005,
    'recovery_time': '12:30',
    'rec_divergence_pct': 0.010,
    'rec_timed_exit': True,
    'rec_timed_exit_hour': 14
}

success, data, _ = run_bot4_backtest(params)

if success:
    m = data['metrics']
    print("Net PnL:", m['net_pnl'])
    print("Win Rate:", m['win_rate_pct'])
    print("Total Trades:", m['total_trades'])
    print("Winning Trades:", m['winning_trades'])
    print("Losing Trades:", m['losing_trades'])
    
    # Check that specific trade on 2022-01-28
    for t in data['trades']:
        if t['entry_time'].startswith('2022-01-28'):
            print(f"Trade on 2022-01-28: {json.dumps(t, indent=2)}")
else:
    print("Failed")
