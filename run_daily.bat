@echo off
chcp 65001 >nul
title GitHub AI 日报

echo ========================================
echo    GitHub AI 日报 - 正在运行...
echo ========================================
echo.

python "%~dp0github_ai_daily.py"

echo.
echo 按任意键退出...
pause >nul
