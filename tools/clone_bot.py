import os
import shutil
import sys
import re

def main():
    if len(sys.argv) < 2:
        print("Usage: python clone_bot.py <new_bot_name>")
        print("Example: python tools/clone_bot.py bot7")
        sys.exit(1)

    new_bot = sys.argv[1].lower()
    
    if not new_bot.startswith("bot"):
        print("Error: The new bot name should ideally start with 'bot' (e.g. bot7)")
        sys.exit(1)

    if os.path.exists(new_bot):
        print(f"Error: Directory {new_bot} already exists!")
        sys.exit(1)

    # Calculate capitalizations
    # e.g., bot7 -> Bot7 -> BOT7
    new_bot_cap = new_bot.capitalize()
    new_bot_up = new_bot.upper()

    print(f"Cloning bot6 into {new_bot}...")
    
    # 1. Copy the main bot directory
    shutil.copytree("bot6", new_bot)

    def replace_in_file(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # We replace longest and most specific first if needed, but here they are disjoint mostly
        # Actually replace BOT6 first, then Bot6, then bot6
        new_content = content.replace("BOT6", new_bot_up)
        new_content = new_content.replace("Bot6", new_bot_cap)
        new_content = new_content.replace("bot6", new_bot)

        if new_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)

    # 2. Update files inside the new bot directory
    for root, dirs, files in os.walk(new_bot):
        for filename in files:
            if filename.endswith(".py") or filename.endswith(".md"):
                replace_in_file(os.path.join(root, filename))

    # 3. Copy and update live strategy
    live_strat_src = "strategies/scripts/bot6_live_strategy.py"
    live_strat_dst = f"strategies/scripts/{new_bot}_live_strategy.py"
    if os.path.exists(live_strat_src):
        shutil.copyfile(live_strat_src, live_strat_dst)
        replace_in_file(live_strat_dst)
        print(f"Created {live_strat_dst}")

    # 4. Copy and update scanner script
    # Note: original scanner was scanner.py. 
    scanner_src = "strategies/scripts/scanner.py"
    scanner_dst = f"strategies/scripts/scanner_{new_bot}.py"
    if os.path.exists(scanner_src):
        shutil.copyfile(scanner_src, scanner_dst)
        replace_in_file(scanner_dst)
        print(f"Created {scanner_dst}")

    # 5. Inject into frontend/src/pages/Backtest.tsx
    backtest_tsx = "frontend/src/pages/Backtest.tsx"
    if os.path.exists(backtest_tsx):
        with open(backtest_tsx, 'r', encoding='utf-8') as f:
            tsx_content = f.read()

        # Inject into botLabel
        if new_bot not in tsx_content:
            # Look for the last bot return e.g., if (bot === 'bot6b') ...
            tsx_content = re.sub(
                r"(if \(bot === 'bot6b'\) return 'Bot 6b \(Scanner Clone\)')",
                f"\\1\n    if (bot === '{new_bot}') return '{new_bot_cap} (Scanner Clone)'",
                tsx_content
            )

            # Inject into Paper Trade dropdown filter
            tsx_content = re.sub(
                r'(<SelectItem value="bot6b">Bot 6b \(Scanner\)</SelectItem>)',
                f'\\1\n                <SelectItem value="{new_bot}">{new_bot_cap} (Scanner Clone)</SelectItem>',
                tsx_content
            )

            # Inject into Scanner Tab dropdown
            tsx_content = re.sub(
                r'(<SelectItem value="bot6b">Bot 6b Scanner \(Stocks Clone\)</SelectItem>)',
                f'\\1\n                      <SelectItem value="{new_bot}">{new_bot_cap} Scanner (Stocks Clone)</SelectItem>',
                tsx_content
            )

            with open(backtest_tsx, 'w', encoding='utf-8') as f:
                f.write(tsx_content)
            print(f"Injected {new_bot} into Backtest.tsx")

    # 6. Inject into services/backtest_scanner_service.py
    service_py = "services/backtest_scanner_service.py"
    if os.path.exists(service_py):
        with open(service_py, 'r', encoding='utf-8') as f:
            svc_content = f.read()
        
        if new_bot not in svc_content:
            # We look for the list: if bot_id not in ["bot6", "bot6b"]:
            # and append to it
            match = re.search(r'if bot_id not in \[(.*?)\]:', svc_content)
            if match:
                current_list = match.group(1)
                new_list = current_list + f', "{new_bot}"'
                svc_content = svc_content.replace(f'if bot_id not in [{current_list}]:', f'if bot_id not in [{new_list}]:')
                with open(service_py, 'w', encoding='utf-8') as f:
                    f.write(svc_content)
                print(f"Injected {new_bot} into backtest_scanner_service.py")

    print(f"\nSuccessfully cloned bot6 to {new_bot}! You can now use it in the UI and CLI.")

if __name__ == "__main__":
    main()
