@echo off
title LifeOS Server

REM check if service already running
powershell -NoProfile -Command "try{Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2|Out-Null;exit 0}catch{exit 1}" >nul 2>&1
if %errorlevel%==0 (
    echo [LifeOS] Already running. Opening browser...
    start http://127.0.0.1:8000
    timeout /t 2 >nul
    exit /b 0
)

echo [LifeOS] Starting server...
cd /d "%~dp0apps\server"

REM open browser after short delay
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"

REM run server in foreground (close this window to stop)
set "PYTHONPATH=%~dp0apps\server"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo [LifeOS] Server stopped.
pause