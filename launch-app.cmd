@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Preparing Market Navigator for first use...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    python -m venv .venv
  )
  if errorlevel 1 goto :failed
  ".venv\Scripts\python.exe" -m pip install -e .
  if errorlevel 1 goto :failed
)

start "" ".venv\Scripts\pythonw.exe" -m csi300_service.desktop
goto :end

:failed
echo.
echo Setup failed. Python 3.11 or newer and internet access are required for first use.
pause

:end
endlocal
