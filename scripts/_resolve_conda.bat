@echo off
rem Helper called from other .bat scripts via `call scripts\_resolve_conda.bat`.
rem Sets CONDA_EXE to a usable conda executable so subsequent
rem `"%CONDA_EXE%" run -n py313 ...` works even when cmd.exe was launched
rem without `conda init`. Exits the caller with code 1 if conda is not found.

if defined CONDA_EXE if exist "%CONDA_EXE%" goto :done

where conda >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%i in ('where conda') do (
        set "CONDA_EXE=%%i"
        goto :done
    )
)

rem Common Windows install locations.
for %%p in (
    "%USERPROFILE%\miniconda3\Scripts\conda.exe"
    "%USERPROFILE%\anaconda3\Scripts\conda.exe"
    "%USERPROFILE%\AppData\Local\miniconda3\Scripts\conda.exe"
    "%USERPROFILE%\AppData\Local\anaconda3\Scripts\conda.exe"
    "%ProgramData%\miniconda3\Scripts\conda.exe"
    "%ProgramData%\anaconda3\Scripts\conda.exe"
    "%ProgramData%\Anaconda3\Scripts\conda.exe"
    "C:\miniconda3\Scripts\conda.exe"
    "C:\anaconda3\Scripts\conda.exe"
) do (
    if exist "%%~p" (
        set "CONDA_EXE=%%~p"
        goto :done
    )
)

echo Conda executable not found. Install Miniconda/Anaconda or set CONDA_EXE 1>&2
echo to the full path of conda.exe before running this script. 1>&2
exit /b 1

:done
exit /b 0
