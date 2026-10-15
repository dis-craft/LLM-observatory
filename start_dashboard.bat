@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found.
  echo Install Python 3.10+ from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating local Python environment...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Could not create the virtual environment. Check your Python installation.
    pause
    exit /b 1
  )
)

echo Installing or updating dashboard dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Starting LLM Observatory at http://127.0.0.1:8501
echo Keep this window open while using the dashboard.
echo Press Ctrl+C to stop the local server.
start "" "http://127.0.0.1:8501"
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8501
goto :eof

:error
echo Dashboard setup failed. Read the error above.
pause
exit /b 1
