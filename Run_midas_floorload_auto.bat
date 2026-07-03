@echo off
setlocal EnableExtensions

REM MIDAS FLOOR LOAD TOOL launcher
REM This BAT intentionally uses ASCII-only text and CRLF line endings.
REM Reason: Korean/UTF-8 text inside BAT can be misread by Windows CMD on some PCs.

cd /d "%~dp0"

if not exist "logs" mkdir "logs"
set "LOG=%~dp0logs\launcher.log"

echo ============================================================ > "%LOG%"
echo MIDAS FLOOR LOAD TOOL launcher log >> "%LOG%"
echo Date: %date% %time% >> "%LOG%"
echo Root: %~dp0 >> "%LOG%"
echo ============================================================ >> "%LOG%"

echo.
echo [1/4] Checking project files...
if not exist "app\main.py" (
    echo ERROR: app\main.py was not found.
    echo ERROR: app\main.py was not found. >> "%LOG%"
    echo.
    echo Put this BAT file in the same folder as the app folder.
    echo.
    pause
    exit /b 1
)

echo [2/4] Preparing DATA and logs folders...
for %%D in (
    "DATA"
    "DATA\dxf_templates"
    "DATA\imported_dxf"
    "DATA\mgt"
    "DATA\models"
    "DATA\reports"
    "DATA\pdf_jobs"
    "logs"
) do (
    if not exist "%%~D" mkdir "%%~D" >> "%LOG%" 2>&1
)

echo [3/4] Selecting Python...
set "RUN_OK="

if exist ".venv\Scripts\python.exe" (
    echo Trying .venv Python...
    echo Command: .venv\Scripts\python.exe -m app.main >> "%LOG%"
    ".venv\Scripts\python.exe" -m app.main >> "%LOG%" 2>&1
    if not errorlevel 1 (
        set "RUN_OK=1"
    ) else (
        echo WARNING: .venv Python failed. Retrying with system Python...
        echo WARNING: .venv Python failed. Retrying with system Python. >> "%LOG%"
    )
)

if not defined RUN_OK (
    echo Trying system Python...
    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: python command was not found.
        echo ERROR: python command was not found. >> "%LOG%"
        echo.
        echo Install Python or add Python to PATH.
        echo.
        pause
        exit /b 1
    )

    echo Command: python -m app.main >> "%LOG%"
    python -m app.main >> "%LOG%" 2>&1
    if not errorlevel 1 (
        set "RUN_OK=1"
    )
)

if not defined RUN_OK (
    echo.
    echo ERROR: Program failed to start.
    echo ERROR: Program failed to start. >> "%LOG%"
    echo.
    echo Open logs\launcher.log and check the last error message.
    echo.
    pause
    exit /b 1
)

echo.
echo Program closed normally.
echo Program closed normally. >> "%LOG%"
pause
exit /b 0
