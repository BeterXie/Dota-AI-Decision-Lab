@echo off
rem ============================================================================
rem  Dota AI Decision Lab - restart (running -> restart, not running -> start)
rem
rem  - If this project is already running, stop it first and start fresh.
rem  - If nothing is running, just start normally.
rem  - Only python.exe -m app.main under THIS directory is stopped, so other
rem    projects are left untouched.
rem  - Stop / log rotation / start / health check reuse start-app.cmd (single
rem    source of truth for launch logic).
rem
rem  Double-click this file, or run:  restart-app.bat
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "APP_DIR=%~dp0"

if not exist "%~dp0start-app.cmd" (
    echo [ERROR] start-app.cmd is missing next to restart-app.bat, aborting.
    exit /b 1
)

rem ---- detect whether this project is already running ------------------------
powershell -NoProfile -Command "$dir = $env:APP_DIR.TrimEnd('\'); $alive = $false; if (Test-Path '.runtime\app.pid') { $raw = (Get-Content '.runtime\app.pid' -ErrorAction SilentlyContinue | Select-Object -First 1); if ($raw -match '^\d+$') { $alive = $null -ne (Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue) } }; $matches = @(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*app.main*' -and $_.CommandLine -like ('*' + $dir + '*') }); if ($alive -or $matches.Count -gt 0) { Write-Host '[INFO] detected running instance - restarting...' } else { Write-Host '[INFO] no running instance detected - starting...' }"

rem ---- stop (if running), rotate logs, start fresh, wait for health -----------
call "%~dp0start-app.cmd"
exit /b %errorlevel%
