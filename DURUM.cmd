@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
"%~dp0.venv\Scripts\python.exe" "%~dp0setup\project_status.py" %*
if errorlevel 1 pause
