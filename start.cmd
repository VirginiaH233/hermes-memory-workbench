@echo off
chcp 65001 >nul
title Hermes 记忆工作台
rem Hermes 记忆工作台 —— 启动脚本（Windows）
rem   双击这个文件 = 看自己的真实记忆
rem   想看演示数据：在这个目录开命令行，跑  start.cmd --demo
rem 只依赖 Python 3.9+（标准库），不需要装任何东西。
rem
rem ⚠️ 这个文件必须是 CRLF 换行。LF 换行的 .cmd 在 cmd.exe 里会被整段错行解析
rem    （实测：双击「没有任何反应」，或报一行看不懂的「不是内部或外部命令」）。
rem    所以仓库里也存 CRLF（.gitattributes 里写成 *.cmd -text，否则 git 会把换行归一成 LF，
rem    从 GitHub 下载 zip 的人拿到的就是坏的）。

set "PY="
rem ① 优先用 Hermes 自带的 Python（装了 Hermes 就一定有）
if exist "%LOCALAPPDATA%\hermes\hermes-agentenv\Scripts\python.exe" set "PY=%LOCALAPPDATA%\hermes\hermes-agentenv\Scripts\python.exe"
rem ② 退而求其次：系统里的 python
if defined PY goto :found
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if defined PY goto :found

echo 找不到 Python。装一个再来：https://www.python.org/downloads/
echo （安装时记得勾上 "Add python.exe to PATH"）
pause
exit /b 1

:found
echo 正在启动，浏览器会自动打开...
echo.
"%PY%" "%~dp0server.py" %*
echo.
echo 已停止。这个窗口可以关掉了。
pause
