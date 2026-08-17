@echo off
rem ============================================================================
rem  Dota AI Decision Lab - local development login
rem
rem  Starts the normal application with real OTP/session/entitlement logic, but
rem  writes login codes to .runtime\local-login-code.txt instead of Resend.
rem  The configured development email receives GLOBAL Pro entitlements.
rem ============================================================================
setlocal EnableExtensions
cd /d "%~dp0"

if not exist .runtime mkdir .runtime

set "LOCAL_AUTH_SECRET_FILE=.runtime\local-auth-secret.txt"
if not exist "%LOCAL_AUTH_SECRET_FILE%" (
    if not exist ".venv\Scripts\python.exe" (
        echo FAILED - .venv\Scripts\python.exe not found. Create the project virtualenv first.
        exit /b 1
    )
    ".venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(48))" > "%LOCAL_AUTH_SECRET_FILE%"
)

set /p "AUTH_SECRET_KEY="<"%LOCAL_AUTH_SECRET_FILE%"
if not defined AUTH_SECRET_KEY (
    echo FAILED - could not load local auth secret.
    exit /b 1
)

set "AUTH_ENABLED=true"
set "AUTH_COOKIE_SECURE=false"
set "DOTA_LOCAL_AUTH_ENABLED=true"
if not defined DOTA_LOCAL_AUTH_EMAIL set "DOTA_LOCAL_AUTH_EMAIL=dev@localhost"
set "DOTA_LOCAL_AUTH_CODE_PATH=.runtime\local-login-code.txt"
del /q "%DOTA_LOCAL_AUTH_CODE_PATH%" >nul 2>&1

call start-app.cmd
if errorlevel 1 exit /b %errorlevel%

echo.
echo Local development login is enabled.
echo Pro test account: %DOTA_LOCAL_AUTH_EMAIL%
echo After requesting a login code, run:
echo   type %DOTA_LOCAL_AUTH_CODE_PATH%
echo Any other local email can also log in, but will remain Free unless granted separately.
exit /b 0
