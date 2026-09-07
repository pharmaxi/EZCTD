@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create the local environment first. See docs\development\WORKBENCH_0_3.md
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m ezctd.workbench
if errorlevel 1 pause
endlocal
