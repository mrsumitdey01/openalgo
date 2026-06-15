@echo off
title OPENALGO BOT 4 - PAPER TRADE DAEMON
echo ========================================================
echo        OPENALGO - BOT 4 PAPER TRADING DAEMON
echo ========================================================
echo.

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo Error: Virtual environment not found. Please ensure .venv exists in this directory.
    pause
    exit /b
)

call .venv\Scripts\activate.bat
set PAPER_MODE=true

echo Initializing execution engine for NIFTY 09:30 Straddle...
echo PAPER_MODE is strictly enforced to TRUE.
echo This terminal must remain open to continue trading.
echo Your UI will automatically synchronize with this daemon.
echo.

python strategies\scripts\bot4_straddle_seller.py

echo.
echo Daemon execution halted.
pause
