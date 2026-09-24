@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" launcher\start_studentlog.py
) else (
  python launcher\start_studentlog.py
)
if errorlevel 1 pause
