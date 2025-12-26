@echo off
echo Starting JKM Trading Bot V1...
echo --------------------------------
echo 1. Starting Backend (Web App)...
start "JKM Backend (Do not close)" uvicorn web_app:app --host 0.0.0.0 --port 8000 --reload

echo Waiting 5 seconds for backend...
timeout /t 5 >nul

echo 2. Starting Telegram Client...
start "JKM Telegram Bot (Do not close)" python telegram_bot.py

echo --------------------------------
echo Done! Two new windows should have opened.
echo You can minimize them, but don't close them.
pause
