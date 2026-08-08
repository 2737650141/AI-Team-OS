@echo off
rem AI Team OS one-click launcher. Opens the browser after both services are healthy.
rem Loopback only. No administrator rights or API key are required for Demo Mode.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_ai_team_os.ps1"
