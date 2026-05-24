@echo off
rem Daily-report entry point for the Windows scheduled task. Invokes the
rem Python orchestrator under conda env py313. Logs go to
rem data\artifacts\scheduled\last_run.log (overwritten each run) and a
rem timestamped sibling YYYYMMDD-HHMM.log.
rem
rem MARKET_HELPER_GDRIVE_ROOT resolution is handled by the Python config
rem layer's Pattern B probe — no shell injection needed.

setlocal
set "ROOT_DIR=%~dp0.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

if "%ENV_NAME%"=="" set "ENV_NAME=py313"

rem Cache dirs (matplotlib / xdg) to avoid scattering temp state under the
rem scheduled-task user's profile.
if "%CACHE_ROOT%"=="" set "CACHE_ROOT=%ROOT_DIR%\.cache"
if "%MPLCONFIGDIR%"=="" set "MPLCONFIGDIR=%CACHE_ROOT%\matplotlib"
if "%XDG_CACHE_HOME%"=="" set "XDG_CACHE_HOME=%CACHE_ROOT%\xdg"
if not exist "%MPLCONFIGDIR%" mkdir "%MPLCONFIGDIR%"
if not exist "%XDG_CACHE_HOME%" mkdir "%XDG_CACHE_HOME%"

call "%~dp0_resolve_conda.bat"
if errorlevel 1 (
    echo Could not resolve conda; aborting.
    exit /b 1
)

pushd "%ROOT_DIR%"
"%CONDA_EXE%" run -n "%ENV_NAME%" python "%ROOT_DIR%\scripts\dev\run_daily_report.py"
set "EXIT_CODE=%ERRORLEVEL%"
popd

endlocal & exit /b %EXIT_CODE%
