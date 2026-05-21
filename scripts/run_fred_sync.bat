@echo off
rem Sync the FRED macro panel used by the regime-detection macro_regime method.
rem
rem FRED_API_KEY is read by the Python side from MARKET_HELPER_CONFIG_PATH /
rem configs/portfolio_monitor/local.env / the process environment — no shell
rem sourcing needed here. See market_helper.workflows.sync_fred_macro_panel.
setlocal

set "ROOT_DIR=%~dp0.."
call "%~dp0_resolve_conda.bat"
if errorlevel 1 exit /b 1
pushd "%ROOT_DIR%"

if "%FRED_SERIES_CONFIG%"=="" set "FRED_SERIES_CONFIG=configs\regime_detection\fred_series.yml"
if "%FRED_CACHE_DIR%"=="" set "FRED_CACHE_DIR=data\interim\fred"
if "%FRED_OBSERVATION_START%"=="" set "FRED_OBSERVATION_START=2005-01-01"
if "%FRED_FORCE_REFRESH%"=="" set "FRED_FORCE_REFRESH=0"

if not exist "%FRED_SERIES_CONFIG%" (
    echo Missing FRED series config: %FRED_SERIES_CONFIG% 1>&2
    popd
    exit /b 1
)

set "FORCE_FLAG="
if /i "%FRED_FORCE_REFRESH%"=="1" set "FORCE_FLAG=--force"
if /i "%FRED_FORCE_REFRESH%"=="true" set "FORCE_FLAG=--force"

"%CONDA_EXE%" run -n py313 python -m market_helper.cli.main fred-macro-sync ^
    --config "%FRED_SERIES_CONFIG%" ^
    --cache-dir "%FRED_CACHE_DIR%" ^
    --observation-start "%FRED_OBSERVATION_START%" ^
    %FORCE_FLAG%
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%
