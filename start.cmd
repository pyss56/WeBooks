@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在停止已有进程...
taskkill /f /im python.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo 正在启动企业微信记账助手...
call python.exe app.py
pause
