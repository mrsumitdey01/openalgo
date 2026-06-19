import re

def minify(filepath):
    with open(filepath, 'r') as f:
        code = f.read()
    # Remove docstrings
    code = re.sub(r'\"\"\"[\s\S]*?\"\"\"', '', code)
    code = re.sub(r"\'\'\'[\s\S]*?\'\'\'", '', code)
    # Remove single line comments
    code = re.sub(r'#.*', '', code)
    # Remove empty lines
    lines = [line for line in code.split('\n') if line.strip()]
    return '\n'.join(lines)

b4 = minify(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\strategies\scripts\bot4_straddle_seller.py')
b5 = minify(r'C:\Users\sumit\.gemini\antigravity\worktrees\OpenAlgo\work-on-openalgo\strategies\scripts\bot5_straddle_seller.py')
print('Bot 4 minified chars:', len(b4))
print('Bot 5 minified chars:', len(b5))
