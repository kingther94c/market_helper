@echo off
setlocal

set "ROOT_DIR=%~dp0.."
if "%ENV_NAME%"=="" set "ENV_NAME=py313"
if "%HOST%"=="" set "HOST=127.0.0.1"
if "%PORT%"=="" set "PORT=8080"
if "%AUTO_OPEN%"=="" set "AUTO_OPEN=1"
set "URL=http://%HOST%:%PORT%/portfolio"

if "%CACHE_ROOT%"=="" set "CACHE_ROOT=%ROOT_DIR%\.cache"
if "%MPLCONFIGDIR%"=="" set "MPLCONFIGDIR=%CACHE_ROOT%\matplotlib"
if "%XDG_CACHE_HOME%"=="" set "XDG_CACHE_HOME=%CACHE_ROOT%\xdg"
set "MARKET_HELPER_UI_SHOW=0"

call "%~dp0_resolve_conda.bat"
if errorlevel 1 exit /b 1

if not exist "%MPLCONFIGDIR%" mkdir "%MPLCONFIGDIR%"
if not exist "%XDG_CACHE_HOME%" mkdir "%XDG_CACHE_HOME%"

echo Starting Portfolio Monitor at %URL%
if not "%AUTO_OPEN%"=="0" (
    rem Browsers retry the connection — opening before the server is fully up is fine.
    start "" "%URL%"
)

pushd "%ROOT_DIR%"
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m market_helper.presentation.dashboard.app --host "%HOST%" --port "%PORT%" --no-show
set "EXIT_CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %EXIT_CODE%
