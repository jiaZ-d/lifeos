@echo off
title LifeOS Stop

echo [LifeOS] Stopping server...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'uvicorn.*app\.main:app' -and $_.CommandLine -match 'port 8000' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('Stopped PID ' + $_.ProcessId) }"
timeout /t 1 >nul
powershell -NoProfile -Command "try{Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -UseBasicParsing -TimeoutSec 2|Out-Null; Write-Host '[LifeOS] WARNING: still running!'; exit 1}catch{Write-Host '[LifeOS] Server stopped.'; exit 0}"
echo.
pause