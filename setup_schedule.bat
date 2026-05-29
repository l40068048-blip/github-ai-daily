@echo off
chcp 65001 >nul
title 设置 GitHub AI 日报 - 每日自动任务

echo ========================================
echo    设置 GitHub AI 日报自动任务
echo ========================================
echo.
echo 将在每天早上 9:00 自动运行
echo.

:: 获取当前目录
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: 创建计划任务
schtasks /create ^
    /tn "GitHub AI 日报" ^
    /tr "python \"%SCRIPT_DIR%\github_ai_daily.py\"" ^
    /sc daily ^
    /st 09:00 ^
    /f ^
    /ru "%USERNAME%"

if %ERRORLEVEL% equ 0 (
    echo.
    echo ✅ 计划任务创建成功！
    echo.
    echo 📋 任务名称: GitHub AI 日报
    echo ⏰ 运行时间: 每天 09:00
    echo 📂 工作目录: %SCRIPT_DIR%
    echo.
    echo 查看所有计划任务:
    echo   schtasks /query /tn "GitHub AI 日报"
    echo.
    echo 删除任务:
    echo   schtasks /delete /tn "GitHub AI 日报" /f
) else (
    echo.
    echo ❌ 创建失败，请以管理员身份运行此脚本
    echo    右键 -> 以管理员身份运行
)

echo.
pause
