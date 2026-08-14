@echo off
rem ============================================================================
rem  Dota AI Decision Lab - one-click start (stop current instance, start fresh)
rem
rem  - Stops THIS project's instance via the PID file (.runtime\app.pid) with a
rem    command-line sweep scoped to this directory as a fallback, so other
rem    python projects are left untouched regardless of the folder name.
rem  - Rotates .runtime logs with a timestamp before starting.
rem  - Reads the web port from .env PORT= (default 8000).
rem  - Waits for the runtime API to become healthy AND verifies the NEW
rem    process is still alive before printing OK (no false positives).
rem
rem  Double-click this file, or run:  start-app.cmd
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "APP_DIR=%~dp0"

if not exist .runtime mkdir .runtime

rem ---- 1) resolve the web port from .env -------------------------------------
set "APP_PORT="
for /f "usebackq tokens=2 delims==" %%a in (`findstr /b "PORT=" .env 2^>nul`) do set "APP_PORT=%%a"
if not defined APP_PORT set "APP_PORT=8000"

rem ---- 2) stop this project's running instance -------------------------------
powershell -NoProfile -Command "$pidFile = '.runtime\app.pid'; if (Test-Path $pidFile) { $old = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1); if ($old -match '^\d+$') { $proc = Get-Process -Id ([int]$old) -ErrorAction SilentlyContinue; if ($proc) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } }; Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "$dir = $env:APP_DIR.TrimEnd('\'); Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*app.main*' -and $_.CommandLine -like ('*' + $dir + '*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
powershell -NoProfile -Command "Start-Sleep -Seconds 3"

rem ---- 3) rotate previous logs (after the old instance released them) ----------
powershell -NoProfile -Command "$ts = Get-Date -Format 'yyyyMMdd-HHmmss'; if (Test-Path '.runtime\app-main.stdout.log') { Move-Item -Force '.runtime\app-main.stdout.log' (\".runtime\app-main.stdout.$ts.log\"); Move-Item -Force '.runtime\app-main.stderr.log' (\".runtime\app-main.stderr.$ts.log\") }"

rem ---- 4) start the runtime detached, logs to .runtime, PID recorded -----------
powershell -NoProfile -Command "$p = Start-Process -FilePath '%~dp0.venv\Scripts\python.exe' -ArgumentList '-m','app.main' -WorkingDirectory '%~dp0' -RedirectStandardOutput '%~dp0.runtime\app-main.stdout.log' -RedirectStandardError '%~dp0.runtime\app-main.stderr.log' -WindowStyle Hidden -PassThru; Set-Content -Path '.runtime\app.pid' -Value $p.Id"

rem ---- 5) wait for health AND verify the new process survived ------------------
powershell -NoProfile -Command "$pidFile = '.runtime\app.pid'; $newId = 0; if (Test-Path $pidFile) { $raw = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1); if ($raw -match '^\d+$') { $newId = [int]$raw } }; $ok=$false; foreach($i in 1..20){ try { $r=Invoke-WebRequest -Uri ('http://127.0.0.1:'+$env:APP_PORT+'/api/runtime') -TimeoutSec 5 -UseBasicParsing; if($r.StatusCode -eq 200){$ok=$true;break} } catch {}; Start-Sleep -Seconds 3 }; $alive = ($newId -ne 0) -and ($null -ne (Get-Process -Id $newId -ErrorAction SilentlyContinue)); if($ok -and $alive){ Write-Host ('OK - runtime healthy at http://127.0.0.1:'+$env:APP_PORT+' (pid '+$newId+')') } else { Write-Host ('FAILED - healthy='+$ok+' alive='+$alive+' (see .runtime\app-main.stderr.log)'); exit 1 }"
exit /b %errorlevel%
