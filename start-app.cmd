@echo off
rem ============================================================================
rem  Dota AI Decision Lab - one-click start (stop current instance, start fresh)
rem
rem  - Only stops THIS project's app.main processes (other python projects are
rem    left untouched).
rem  - Rotates .runtime logs with a timestamp before starting.
rem  - Reads the web port from .env PORT= (default 8000).
rem  - Waits for the runtime API to become healthy and prints the result.
rem
rem  Double-click this file, or run:  start-app.cmd
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

if not exist .runtime mkdir .runtime

rem ---- 1) resolve the web port from .env -------------------------------------
set "APP_PORT="
for /f "usebackq tokens=2 delims==" %%a in (`findstr /b "PORT=" .env 2^>nul`) do set "APP_PORT=%%a"
if not defined APP_PORT set "APP_PORT=8000"

rem ---- 2) stop this project's running instances -------------------------------
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*app.main*' -and $_.CommandLine -like '*Dota AI Decision Lab*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "Start-Sleep -Seconds 3"

rem ---- 3) rotate previous logs (after the old instance released them) ----------
powershell -NoProfile -Command "$ts = Get-Date -Format 'yyyyMMdd-HHmmss'; if (Test-Path '.runtime\app-main.stdout.log') { Move-Item -Force '.runtime\app-main.stdout.log' (\".runtime\app-main.stdout.$ts.log\"); Move-Item -Force '.runtime\app-main.stderr.log' (\".runtime\app-main.stderr.$ts.log\") }"

rem ---- 4) start the runtime detached, logs to .runtime -------------------------
powershell -NoProfile -Command "Start-Process -FilePath '%~dp0.venv\Scripts\python.exe' -ArgumentList '-m','app.main' -WorkingDirectory '%~dp0' -RedirectStandardOutput '%~dp0.runtime\app-main.stdout.log' -RedirectStandardError '%~dp0.runtime\app-main.stderr.log' -WindowStyle Hidden"

rem ---- 5) wait for the runtime API to become healthy ---------------------------
powershell -NoProfile -Command "$ok=$false; foreach($i in 1..20){ try { $r=Invoke-WebRequest -Uri ('http://127.0.0.1:'+$env:APP_PORT+'/api/runtime') -TimeoutSec 5 -UseBasicParsing; if($r.StatusCode -eq 200){$ok=$true;break} } catch {}; Start-Sleep -Seconds 3 }; if($ok){ Write-Host ('OK - runtime healthy at http://127.0.0.1:'+$env:APP_PORT) } else { Write-Host 'FAILED - runtime not healthy within 60s (see .runtime\app-main.stderr.log)'; exit 1 }"
exit /b %errorlevel%
