@echo off
setlocal
cd /d "%~dp0"
py -3.12 setup_app.py
if errorlevel 1 (
  echo Setup failed. See the error above and README.md.
  pause
  exit /b 1
)
pause
