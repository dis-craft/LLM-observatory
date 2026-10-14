@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.10+ from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Could not create a Python virtual environment. Check your Python installation.
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :error
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :error
.venv\Scripts\python.exe -m streamlit run app.py
if errorlevel 1 goto :error
goto :eof
:error
echo Dashboard startup failed. Read the errors above.
pause
exit /b 1
