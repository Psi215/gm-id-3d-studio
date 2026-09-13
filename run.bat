@echo off
rem gm/ID 设计数据工作室 - Windows 启动脚本
rem 解释器查找顺序: 仓库内 .venv -> 上层工作区 .venv -> 系统 pythonw
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
) else if exist "..\.venv\Scripts\pythonw.exe" (
    start "" "..\.venv\Scripts\pythonw.exe" "%~dp0main.py" %*
) else (
    start "" pythonw "%~dp0main.py" %*
)
endlocal
