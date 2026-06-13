import sys

path = 'services/backtest_mcx_service.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Only replace in run_bot2_mcx_backtest
import re

# We will split the file around run_bot2_mcx_backtest to ensure we don't touch bot1
parts = content.split('def run_bot2_mcx_backtest(params: dict) -> tuple[bool, dict, int]:')
if len(parts) == 2:
    top = parts[0]
    bot2 = 'def run_bot2_mcx_backtest(params: dict) -> tuple[bool, dict, int]:' + parts[1]

    bot2 = bot2.replace('from strategies.scripts.bot2_mcx_hull_dtc import HullBBI, DTCRibbon, check_signals', 
                        'from strategies.scripts.bot2_mcx_bb_trend import BollingerTrendFilter, check_signals')
    
    # Handle windows vs unix newlines
    bot2 = re.sub(r'hull = HullBBI\(length=21\)\s+df = hull\.compute\(df\)\s+dtc = DTCRibbon\(\)\s+df = dtc\.compute\(df\)', 
                  'bb_trend = BollingerTrendFilter(bb_period=20, bb_std=2.0, rsi_period=14, ema_period=200)\n        df = bb_trend.compute(df)', 
                  bot2)
                  
    bot2 = bot2.replace('"strategy": "bot1_mcx_hull_dtc"', '"strategy": "bot2_mcx_bb_trend"')
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(top + bot2)
    print("Successfully replaced Bot 2 logic")
else:
    print("Could not find run_bot2_mcx_backtest")
