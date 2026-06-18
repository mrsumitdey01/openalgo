import re

with open('services/backtest_service.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r'(def run_bot4_backtest\(params: dict\) -> tuple\[bool, dict, int\]:.*?)(?=\n^def |\Z)'
match = re.search(pattern, content, re.DOTALL | re.MULTILINE)

if match:
    bot4_code = match.group(1)
    
    bot5_code = bot4_code.replace('bot4', 'bot5')
    bot5_code = bot5_code.replace('Bot 4', 'Bot 5')
    bot5_code = bot5_code.replace('Bot4', 'Bot5')
    
    with open('services/backtest_service.py', 'a', encoding='utf-8') as f:
        f.write('\n\n' + bot5_code + '\n')
    print('Bot 5 backtest appended successfully')
else:
    print('run_bot4_backtest not found')
