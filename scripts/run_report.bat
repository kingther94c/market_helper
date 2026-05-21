@echo off
rem Thin Windows wrapper around `python -m market_helper.cli.main <subcommand>`.
rem Unlike scripts\run_report.sh, this does NOT auto-resolve account-env defaults
rem (DEFAULT_PROD_ACCOUNT_ID etc.) — pass --account explicitly, or use the
rem NiceGUI dashboard (scripts\launch_ui.bat) which reads local.env directly.
rem
rem Modes (matches run_report.sh):
rem   snapshot                 -> position-report
rem   ibkr-json                -> ibkr-position-report
rem   ibkr-live                -> ibkr-live-position-report
rem   risk-html / combined-html-> combined-html-report
rem   security-reference-sync  -> security-reference-sync
rem   etf-sector-sync          -> etf-sector-sync
rem   mapping-table            -> extract-report-mapping
rem
rem Composite "ibkr-live-html" / "ibkr-live-combined-html" two-step flow:
rem   1. ibkr-live-position-report -> CSV
rem   2. combined-html-report     -> HTML
rem Use the dashboard for the easy GUI version, or invoke each subcommand
rem manually for full control.
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%.."
if "%ENV_NAME%"=="" set "ENV_NAME=py313"

if "%~1"=="" goto :usage
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage

set "MODE=%~1"
shift

set "CLI_CMD="
if /i "%MODE%"=="snapshot"                set "CLI_CMD=position-report"
if /i "%MODE%"=="ibkr-json"               set "CLI_CMD=ibkr-position-report"
if /i "%MODE%"=="ibkr-live"               set "CLI_CMD=ibkr-live-position-report"
if /i "%MODE%"=="risk-html"               set "CLI_CMD=combined-html-report"
if /i "%MODE%"=="combined-html"           set "CLI_CMD=combined-html-report"
if /i "%MODE%"=="security-reference-sync" set "CLI_CMD=security-reference-sync"
if /i "%MODE%"=="etf-sector-sync"         set "CLI_CMD=etf-sector-sync"
if /i "%MODE%"=="mapping-table"           set "CLI_CMD=extract-report-mapping"

if "%CLI_CMD%"=="" (
    echo Unknown or unsupported-on-Windows mode: %MODE% 1>&2
    echo. 1>&2
    goto :usage_fail
)

set "ARGS="
:collect
if "%~1"=="" goto :run
set "ARGS=!ARGS! "%~1""
shift
goto :collect

:run
call "%SCRIPT_DIR%_resolve_conda.bat"
if errorlevel 1 exit /b 1
pushd "%ROOT_DIR%"
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m market_helper.cli.main %CLI_CMD% %ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%

:usage
echo Usage: scripts\run_report.bat ^<mode^> [CLI args...]
echo.
echo Modes (each forwards remaining args to the matching CLI subcommand):
echo   snapshot                 -^> position-report
echo   ibkr-json                -^> ibkr-position-report
echo   ibkr-live                -^> ibkr-live-position-report ^(pass --account explicitly^)
echo   risk-html / combined-html -^> combined-html-report
echo   security-reference-sync  -^> security-reference-sync
echo   etf-sector-sync          -^> etf-sector-sync
echo   mapping-table            -^> extract-report-mapping
echo.
echo For the composite ibkr-live -^> HTML flow on Windows, use the dashboard
echo ^(scripts\launch_ui.bat^) or run the two CLI subcommands manually.
endlocal & exit /b 0

:usage_fail
echo Run "scripts\run_report.bat --help" for the supported modes. 1>&2
endlocal & exit /b 1
