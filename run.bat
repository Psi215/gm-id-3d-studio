@echo off
rem gm/ID 设计数据浏览器 - Windows 启动脚本
rem 优先使用工作区自带的 .venv; 没有则退回系统 python
setlocal
cd /d "%~dp0"
if exist "..\.venv\Scripts\pythonw.exe" (
    start "" "..\.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
) else (
    start "" pythonw "%~dp0main.py" %*
)
endlocal
