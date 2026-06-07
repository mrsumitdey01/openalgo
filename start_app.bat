@echo off
title OpenAlgo Server
echo ===================================================
echo Starting OpenAlgo Trading Server...
echo ===================================================

:: Navigate to the directory where this script is located
cd /d "%~dp0"

:: Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo Error: Virtual environment not found. Please ensure .venv exists.
    pause
    exit /b
)

:: Activate virtual environment and start the app
call .venv\Scripts\activate.bat
python app.py

:: Pause if the app crashes or stops so you can read the error
echo.
echo Server has stopped.
pause
