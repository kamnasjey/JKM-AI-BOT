@echo off
setlocal
cd /d %~dp0
if /I "%~1"=="demo" (
	set IG_IS_DEMO=true
	echo Starting JKM Trading AI Web (DEMO) on http://127.0.0.1:8000
) else if /I "%~1"=="live" (
	set IG_IS_DEMO=false
	echo Starting JKM Trading AI Web (LIVE) on http://127.0.0.1:8000
) else (
	echo Starting JKM Trading AI Web on http://127.0.0.1:8000
)
echo (Close this window or press Ctrl+C to stop)

"%~dp0.venv\Scripts\python.exe" -m uvicorn web_app:app --reload --host 127.0.0.1 --port 8000

pause
