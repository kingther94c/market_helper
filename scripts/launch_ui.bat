@echo off
setlocal

set "ROOT_DIR=%~dp0.."
if "%ENV_NAME%"=="" set "ENV_NAME=py313"

rem HOST is the *bind* address the dashboard listens on. Default
rem 127.0.0.1 — the dashboard has no auth of its own, so binding broadly
rem (0.0.0.0) would expose it to anything on the LAN / Wi-Fi.
rem
rem For cross-device access from a Tailnet, use **Tailscale Serve**
rem instead of broadening the bind. One-shot setup:
rem   tailscale serve --bg https / http://127.0.0.1:18080
rem Then any tailnet device reaches the report at
rem   https://<this-host>.<tailnet>.ts.net/portfolio/portfolio_dashboard_report.html
rem Tailscale's tunnel + ACLs are the security boundary; the local bind
rem stays loopback-only and the LAN can't see the port.
rem
rem To override (e.g. broaden the bind for a quick same-LAN test), set
rem `set HOST=0.0.0.0` before running this script.
if "%HOST%"=="" set "HOST=127.0.0.1"
rem 18080 instead of the more common 8080 to dodge collisions with Tomcat /
rem Jenkins / Spring Boot / Docker port mappings on developer machines.
if "%PORT%"=="" set "PORT=18080"
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

rem Open a local loading page (file://) instead of the dashboard URL directly.
rem It loads instantly, shows a spinner, polls %URL%, and auto-redirects the
rem moment the server is listening — dodging the cold-start race where the
rem browser reaches the port before Python/uvicorn finishes booting (Chrome
rem does NOT auto-retry a refused connection, so a bare URL shows
rem ERR_CONNECTION_REFUSED until the user manually reloads).
set "LOADING_FILE=%~dp0loading.html"
set "OPEN_TARGET=file:///%LOADING_FILE:\=/%?target=%URL%"
if not exist "%LOADING_FILE%" set "OPEN_TARGET=%URL%"

echo Starting Portfolio Monitor at %URL% (binding on %HOST%:%PORT%)
if not "%AUTO_OPEN%"=="0" (
    start "" "%OPEN_TARGET%"
)

pushd "%ROOT_DIR%"
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m market_helper.presentation.dashboard.app --host "%HOST%" --port "%PORT%" --no-show
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%
