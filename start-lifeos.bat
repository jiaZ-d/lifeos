@echo off
title LifeOS Server

REM read port from config/server.json
for /f %%p in ('powershell -NoProfile -Command "(Get-Content '%~dp0config\server.json' | ConvertFrom-Json).port"') do set PORT=%%p
if "%PORT%"=="" set PORT=8000

REM check if service already running
powershell -NoProfile -Command "try{Invoke-WebRequest ('http://127.0.0.1:%PORT%/api/health') -UseBasicParsing -TimeoutSec 2|Out-Null;exit 0}catch{exit 1}" >nul 2>&1
if %errorlevel%==0 (
    echo [LifeOS] Already running. Opening browser...
    start http://127.0.0.1:%PORT%
    timeout /t 2 >nul
    exit /b 0
)

echo [LifeOS] Starting server (port %PORT%)...
cd /d "%~dp0apps\server"

REM open browser after short delay
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:%PORT%"

REM run server in foreground (close this window to stop); host/port from config/server.json
set "PYTHONPATH=%~dp0apps\server"
".venv\Scripts\python.exe" -m app.main

echo.
echo [LifeOS] Server stopped.
pause
