@echo off
setlocal

set "ROOT_DIR=%~dp0.."
set "ENV_FILE=%ROOT_DIR%\env.yml"
if "%ENV_NAME%"=="" set "ENV_NAME=py313"

call "%~dp0_resolve_conda.bat"
if errorlevel 1 exit /b 1

if not exist "%ENV_FILE%" (
    echo Missing environment definition: %ENV_FILE% 1>&2
    exit /b 1
)

"%CONDA_EXE%" run -n "%ENV_NAME%" python --version >nul 2>nul
if not errorlevel 1 (
    echo Conda environment '%ENV_NAME%' is already installed.
    echo Activate it with: conda activate %ENV_NAME%
    exit /b 0
)

echo Conda environment '%ENV_NAME%' was not found. Recreating it from %ENV_FILE%.
"%CONDA_EXE%" env remove -n "%ENV_NAME%" -y >nul 2>nul
"%CONDA_EXE%" env create -f "%ENV_FILE%"
if errorlevel 1 exit /b 1

echo Installing Playwright Chromium for headless dashboard snapshots...
"%CONDA_EXE%" run -n "%ENV_NAME%" python -m playwright install chromium
if errorlevel 1 exit /b 1

echo Conda environment '%ENV_NAME%' is ready.
echo Activate it with: conda activate %ENV_NAME%
endlocal
