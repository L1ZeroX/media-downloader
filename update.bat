@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" setup_app.py --update
if errorlevel 1 (
  echo Update failed. See the error above.
  pause
  exit /b 1
)
pause
