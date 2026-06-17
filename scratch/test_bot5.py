import sys
sys.path.append(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo')
from services.backtest_service import run_bot5_backtest

params = {
    'strategy': 'bot5_straddle_seller',
    'symbol': 'NIFTY',
    'start_date': '2022-01-01',
    'end_date': '2025-01-01',
    'capital': 185000,
    'lot_size': 65,
    'entry_time': '09:30',
    'exit_time': '15:15',
    'sl_pct': 0.01,
    'max_loss_pct': 0.02,
    'target_type': 'fixed_1600',
    'gap_pct_abort': 0.005,
    'recovery_time': '12:30',
    'rec_divergence_pct': 0.010,
    'rec_timed_exit': True,
    'rec_timed_exit_hour': 14
}

success, data, _ = run_bot5_backtest(params)

if success:
    m = data['metrics']
    print("Bot 5 Net PnL:", m['net_pnl'])
    print("Bot 5 Win Rate:", m['win_rate_pct'])
    print("Bot 5 Total Trades:", m['total_trades'])
else:
    print("Failed")
