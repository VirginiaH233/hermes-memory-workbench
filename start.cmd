@echo off
chcp 65001 >nul
title Hermes 记忆工作台
rem Hermes 记忆工作台 —— 启动脚本（Windows）
rem   双击这个文件 = 看自己的真实记忆
rem   想看演示数据：在这个目录开命令行，跑  start.cmd --demo
rem 只依赖 Python 3.9+（标准库），不需要装任何东西。

set "PY="
rem ① 优先用 Hermes 自带的 Python（装了 Hermes 就一定有）
if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
rem ② 退而求其次：系统里的 python
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"

if not defined PY (
  echo 找不到 Python。装一个再来：https://www.python.org/downloads/
  echo （安装时记得勾上 "Add python.exe to PATH"）
  pause
  exit /b 1
)

echo 正在启动，浏览器会自动打开...
echo.
"%PY%" "%~dp0server.py" %*
echo.
echo 已停止。这个窗口可以关掉了。
pause
