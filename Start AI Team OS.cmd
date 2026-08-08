@echo off
rem AI Team OS 一键启动（010-B 十三：双击 → 浏览器自动打开）
rem 仅监听 127.0.0.1；无需管理员权限；Demo Mode 无需 API Key
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_ai_team_os.ps1"
