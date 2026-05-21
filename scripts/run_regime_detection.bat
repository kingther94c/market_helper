@echo off
setlocal

set "ROOT_DIR=%~dp0.."
call "%~dp0_resolve_conda.bat"
if errorlevel 1 exit /b 1
pushd "%ROOT_DIR%"

set "OUT=%~1"
if "%OUT%"=="" set "OUT=data\artifacts\regime_detection\regime_snapshots.json"
set "MACRO_PANEL=%~2"
if "%MACRO_PANEL%"=="" set "MACRO_PANEL=data\interim\fred\macro_panel.feather"
set "MARKET_PANEL=%~3"
if "%MARKET_PANEL%"=="" set "MARKET_PANEL=data\interim\market_regime\market_panel.feather"

"%CONDA_EXE%" run -n py313 python -m market_helper.cli.main regime-detect ^
    --macro-panel "%MACRO_PANEL%" ^
    --market-panel "%MARKET_PANEL%" ^
    --output "%OUT%"
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%
