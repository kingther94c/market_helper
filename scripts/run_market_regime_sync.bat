@echo off
rem Sync the Yahoo Finance market panel used by the regime-detection market_regime method.
setlocal

set "ROOT_DIR=%~dp0.."
call "%~dp0_resolve_conda.bat"
if errorlevel 1 exit /b 1
pushd "%ROOT_DIR%"

if "%MARKET_REGIME_CONFIG%"=="" set "MARKET_REGIME_CONFIG=configs\regime_detection\market_regime.yml"
if "%MARKET_REGIME_CACHE_DIR%"=="" set "MARKET_REGIME_CACHE_DIR=data\interim\market_regime"
if "%YAHOO_PERIOD%"=="" set "YAHOO_PERIOD=max"
if "%YAHOO_INTERVAL%"=="" set "YAHOO_INTERVAL=1d"

if not exist "%MARKET_REGIME_CONFIG%" (
    echo Missing market regime config: %MARKET_REGIME_CONFIG% 1>&2
    popd
    exit /b 1
)

"%CONDA_EXE%" run -n py313 python -m market_helper.cli.main market-regime-sync ^
    --config "%MARKET_REGIME_CONFIG%" ^
    --cache-dir "%MARKET_REGIME_CACHE_DIR%" ^
    --period "%YAHOO_PERIOD%" ^
    --interval "%YAHOO_INTERVAL%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%
