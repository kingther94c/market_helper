@echo off
setlocal

set "ROOT_DIR=%~dp0.."
if "%ENV_NAME%"=="" set "ENV_NAME=py313"

rem HOST is the *bind* address the dashboard listens on. Default 0.0.0.0
rem so the server is reachable from other devices on the LAN / Tailnet
rem (the iframe report URL like
rem `http://<this-host>:8080/portfolio/portfolio_dashboard_report.html`
rem then works cross-device). Override with `set HOST=127.0.0.1` to scope
rem back to localhost-only. Dashboard has no auth of its own — Tailscale
rem ACLs / Windows Firewall are the security boundary; don't open port
rem 8080 to the public internet.
if "%HOST%"=="" set "HOST=0.0.0.0"
if "%PORT%"=="" set "PORT=8080"
if "%AUTO_OPEN%"=="" set "AUTO_OPEN=1"

rem Browser navigates to a concrete address; 0.0.0.0 is a listen-only
rem sentinel. When HOST is 0.0.0.0 we substitute 127.0.0.1 for the local
rem browser tab; an explicit HOST override is used as-is.
if /I "%HOST%"=="0.0.0.0" (set "OPEN_HOST=127.0.0.1") else (set "OPEN_HOST=%HOST%")
set "URL=http://%OPEN_HOST%:%PORT%/portfolio"

if "%CACHE_ROOT%"=="" set "CACHE_ROOT=%ROOT_DIR%\.cache"
if "%MPLCONFIGDIR%"=="" set "MPLCONFIGDIR=%CACHE_ROOT%\matplotlib"
if "%XDG_CACHE_HOME%"=="" set "XDG_CACHE_HOME=%CACHE_ROOT%\xdg"
set "MARKET_HELPER_UI_SHOW=0"

call "%~dp0_resolve_conda.bat"
if errorlevel 1 exit /b 1

if not exist "%MPLCONFIGDIR%" mkdir "%MPLCONFIGDIR%"
if not exist "%XDG_CACHE_HOME%" mkdir "%XDG_CACHE_HOME%"

echo Starting Portfolio Monitor at %URL% (bound on %HOST%:%PORT%)
if not "%AUTO_OPEN%"=="0" (
    rem Browsers retry the connection — opening before the server is fully up is fine.
    start "" "%URL%"
)

pushd "%ROOT_DIR%"
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m market_helper.presentation.dashboard.app --host "%HOST%" --port "%PORT%" --no-show
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%
