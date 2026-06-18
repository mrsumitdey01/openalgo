import re

with open('frontend/src/pages/Backtest.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. SelectItem
content = content.replace('<SelectItem value="bot4">Bot 4 (Straddle Seller)</SelectItem>', '<SelectItem value="bot4">Bot 4 (Straddle Seller)</SelectItem>\n                      <SelectItem value="bot5">Bot 5 (Straddle Clone)</SelectItem>')

# 2. Render parameters block
pattern = r'({\s*selectedBotAlgorithm === \'bot4\' && \(\s*<div className="space-y-4 pt-4 border-t border-slate-800/60">\s*<div className="flex items-center gap-2 mb-2">.*?</div>\s*\)\s*})'
match = re.search(pattern, content, re.DOTALL)
if match:
    bot4_jsx = match.group(1)
    bot5_jsx = bot4_jsx.replace('bot4', 'bot5').replace('Bot 4', 'Bot 5').replace('Bot4', 'Bot5')
    content = content.replace(bot4_jsx, bot4_jsx + '\n                ' + bot5_jsx)
else:
    print('JSX block not found!')

# 3. hide SL
content = content.replace("selectedBotAlgorithm !== 'bot4'", "selectedBotAlgorithm !== 'bot4' && selectedBotAlgorithm !== 'bot5'")

# 4. execution mode override
content = content.replace("selectedBotAlgorithm === 'bot4' ? 'options_selling'", "(selectedBotAlgorithm === 'bot4' || selectedBotAlgorithm === 'bot5') ? 'options_selling'")

with open('frontend/src/pages/Backtest.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('UI JSX replaced')
