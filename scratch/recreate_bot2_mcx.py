import sys
import re

path = 'services/backtest_mcx_service.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

if 'def run_bot2_mcx_backtest' not in content:
    # Extract run_bot1_mcx_backtest
    parts = content.split('def run_bot1_mcx_backtest(params: dict) -> tuple[bool, dict, int]:')
    bot1_code = 'def run_bot1_mcx_backtest(params: dict) -> tuple[bool, dict, int]:' + parts[1]
    
    bot2_code = bot1_code.replace('run_bot1_mcx_backtest', 'run_bot2_mcx_backtest')
    
    bot2_code = bot2_code.replace('from strategies.scripts.bot1_mcx_hull_dtc import HullBBI, DTCRibbon, check_signals', 
                                  'from strategies.scripts.bot2_mcx_bb_trend import BollingerTrendFilter, check_signals')
    
    bot2_code = re.sub(r'hull = HullBBI\(length=21\)\s+df = hull\.compute\(df\)\s+dtc = DTCRibbon\(\)\s+df = dtc\.compute\(df\)', 
                  'bb_trend = BollingerTrendFilter(bb_period=20, bb_std=2.0, rsi_period=14, ema_period=200)\n        df = bb_trend.compute(df)', 
                  bot2_code)
                  
    bot2_code = bot2_code.replace('"strategy": "bot1_mcx_hull_dtc"', '"strategy": "bot2_mcx_bb_trend"')
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content + "\n\n" + bot2_code)
        
    print("Bot 2 MCX backtest created.")
else:
    print("Already exists")
