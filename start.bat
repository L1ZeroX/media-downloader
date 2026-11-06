@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
start "Youtube Pandora!" ".venv\Scripts\pythonw.exe" "%~dp0main.py"
