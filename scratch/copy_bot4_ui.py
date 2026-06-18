with open('frontend/src/pages/Backtest.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. State Variables
bot4_state = '''  const [bot4TargetType, setBot4TargetType] = useState('fixed_1600')
  const [bot4TrendFilterPct, setBot4TrendFilterPct] = useState('1.0')
  const [bot4RecTimedExit, setBot4RecTimedExit] = useState(true)
  const [bot4RecTimedExitHour, setBot4RecTimedExitHour] = useState('14')'''
bot5_state = bot4_state.replace('bot4', 'bot5').replace('Bot 4', 'Bot 5').replace('Bot4', 'Bot5')
content = content.replace(bot4_state, bot4_state + '\n' + bot5_state)

# 2. handleRunBotBacktest validation
bot4_val = '''    if (selectedBotAlgorithm === 'bot4') {
      if (!bot4TargetType) { showToast.error('Please select Target Mode for Bot 4'); return; }
      if (!bot4TrendFilterPct || Number.parseFloat(bot4TrendFilterPct) < 0) { showToast.error('Please enter valid Trend Filter % for Bot 4'); return; }
    }'''
bot5_val = bot4_val.replace('bot4', 'bot5').replace('Bot 4', 'Bot 5').replace('Bot4', 'Bot5')
content = content.replace(bot4_val, bot4_val + '\n' + bot5_val)

# 3. Payload
bot4_payload = '''      target_type: bot4TargetType, // Specific to Bot 4
      trend_filter_pct: Number.parseFloat(bot4TrendFilterPct) / 100,
      rec_timed_exit: bot4RecTimedExit,
      rec_timed_exit_hour: Number.parseInt(bot4RecTimedExitHour)'''
bot5_payload = '''      ...(selectedBotAlgorithm === 'bot5' ? {
        target_type: bot5TargetType,
        trend_filter_pct: Number.parseFloat(bot5TrendFilterPct) / 100,
        rec_timed_exit: bot5RecTimedExit,
        rec_timed_exit_hour: Number.parseInt(bot5RecTimedExitHour)
      } : {
        target_type: bot4TargetType, // Default back to bot 4 if needed
        trend_filter_pct: Number.parseFloat(bot4TrendFilterPct) / 100,
        rec_timed_exit: bot4RecTimedExit,
        rec_timed_exit_hour: Number.parseInt(bot4RecTimedExitHour)
      })'''
content = content.replace(bot4_payload, bot5_payload)

with open('frontend/src/pages/Backtest.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('UI JS replaced phase 1')
