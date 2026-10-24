@echo off
title LifeOS Restart

REM read port from config/server.json
for /f %%p in ('powershell -NoProfile -Command "(Get-Content '%~dp0config\server.json' | ConvertFrom-Json).port"') do set PORT=%%p
if "%PORT%"=="" set PORT=8000

echo [LifeOS] Stopping old server...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'app\.main' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 >nul

echo [LifeOS] Starting server (port %PORT%)...
cd /d "%~dp0apps\server"
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:%PORT%"
set "PYTHONPATH=%~dp0apps\server"
".venv\Scripts\python.exe" -m app.main

echo.
echo [LifeOS] Server stopped.
pause
