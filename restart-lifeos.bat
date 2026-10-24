@echo off
title LifeOS Restart

echo [LifeOS] Stopping old server...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'uvicorn.*app\.main:app' -and $_.CommandLine -match 'port 8000' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
timeout /t 2 >nul

echo [LifeOS] Starting server...
cd /d "%~dp0apps\server"
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
set "PYTHONPATH=%~dp0apps\server"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo [LifeOS] Server stopped.
pause