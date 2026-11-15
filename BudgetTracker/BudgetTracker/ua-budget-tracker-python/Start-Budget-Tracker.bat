@echo off
setlocal
cd /d "%~dp0"
if not exist "wsgi.py" (
  echo Copy this file into the extracted ua-budget-tracker-python folder first.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\waitress-serve.exe" (
  echo Complete the first-time installation in the Windows LAN guide first.
  pause
  exit /b 1
)
echo UA Budget Tracker - Local Network Server
echo.
echo On this computer: http://localhost:8000
echo Other devices:    http://YOUR-SERVER-IP:8000
 echo Find the server IPv4 address using ipconfig.
echo.
echo Keep this window open. Press Ctrl+C to stop the server.
echo.
".venv\Scripts\waitress-serve.exe" --listen=0.0.0.0:8000 wsgi:app
if errorlevel 1 (
  echo.
  echo The server stopped with an error. Read the message above.
  pause
)
