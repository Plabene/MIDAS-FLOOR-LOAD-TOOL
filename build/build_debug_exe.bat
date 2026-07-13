@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%" || (
  echo [ERROR] Cannot move to project root.
  pause
  exit /b 1
)

set "PY_RUN="
if exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
  set "PY_RUN="%ROOT_DIR%\.venv\Scripts\python.exe""
  goto :python_found
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    set "PY_RUN=py -3.11"
    goto :python_found
  )
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PY_RUN=python"
  goto :python_found
)

echo [ERROR] Python was not found.
echo Install Python 3.11/3.12 or create .venv in the project root.
pause
exit /b 1

:python_found
echo [INFO] Project root: "%ROOT_DIR%"
echo [INFO] Python command: %PY_RUN%
echo.

%PY_RUN% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] PyInstaller is not installed.
  echo Run this command first:
  echo   %PY_RUN% -m pip install pyinstaller pyinstaller-hooks-contrib
  pause
  exit /b 1
)

set "DATA_LEGACY="
set "DATA_USER_CONFIG="
set "DATA_RESOURCES="
set "ICON_ARG="

if exist "%ROOT_DIR%\legacy_v3" set DATA_LEGACY=--add-data "%ROOT_DIR%\legacy_v3;legacy_v3"
if exist "%ROOT_DIR%\user_config" set DATA_USER_CONFIG=--add-data "%ROOT_DIR%\user_config;user_config"
if exist "%ROOT_DIR%\resources" set DATA_RESOURCES=--add-data "%ROOT_DIR%\resources;resources"
if exist "%ROOT_DIR%\resources\app.ico" set ICON_ARG=--icon "%ROOT_DIR%\resources\app.ico"

echo [INFO] Building debug console distribution with PyInstaller...
%PY_RUN% -m PyInstaller --noconfirm --clean --onedir --console --noupx ^
  --name midas_floorload_auto_v4_debug ^
  --paths "%ROOT_DIR%" ^
  --paths "%ROOT_DIR%\legacy_v3\src" ^
  %DATA_LEGACY% ^
  %DATA_USER_CONFIG% ^
  %DATA_RESOURCES% ^
  %ICON_ARG% ^
  --hidden-import pdf_extract ^
  --hidden-import pdf_render ^
  --hidden-import pdf_page_analyzer ^
  --hidden-import table_reconstructor ^
  --hidden-import load_parser ^
  --hidden-import load_classifier ^
  --hidden-import load_case_resolver ^
  --hidden-import manual_overrides ^
  --hidden-import validators ^
  --hidden-import midas_mgtx_writer ^
  --hidden-import midas_mct_writer ^
  --hidden-import floor_load_type_builder ^
  --hidden-import floorload_assignment_builder ^
  --hidden-import floorload_assignment_writer ^
  --hidden-import floorload_validation ^
  --hidden-import name_normalizer ^
  --hidden-import unit_normalizer ^
  --exclude-module pytest ^
  --exclude-module tests ^
  "%ROOT_DIR%\app\main.py"

if errorlevel 1 (
  echo [ERROR] PyInstaller debug build failed.
  pause
  exit /b 1
)

if not exist "%ROOT_DIR%\dist\midas_floorload_auto_v4_debug\midas_floorload_auto_v4_debug.exe" (
  echo [ERROR] Build finished, but debug exe was not found.
  echo Expected: dist\midas_floorload_auto_v4_debug\midas_floorload_auto_v4_debug.exe
  pause
  exit /b 1
)

echo [INFO] Copying runtime data folders to debug dist root...
if exist "%ROOT_DIR%\legacy_v3" (
  robocopy "%ROOT_DIR%\legacy_v3" "%ROOT_DIR%\dist\midas_floorload_auto_v4_debug\legacy_v3" /E /XD __pycache__ .pytest_cache tests /XF *.pyc *.pyo >nul
  if errorlevel 8 (
    echo [ERROR] Failed to copy legacy_v3 to debug distribution folder.
    pause
    exit /b 1
  )
) else (
  echo [ERROR] Required folder not found: legacy_v3
  pause
  exit /b 1
)

if not exist "%ROOT_DIR%\dist\midas_floorload_auto_v4_debug\user_config" mkdir "%ROOT_DIR%\dist\midas_floorload_auto_v4_debug\user_config"
if exist "%ROOT_DIR%\user_config" (
  robocopy "%ROOT_DIR%\user_config" "%ROOT_DIR%\dist\midas_floorload_auto_v4_debug\user_config" *.json /E /XF *.local.json >nul
  if errorlevel 8 (
    echo [ERROR] Failed to copy user_config to debug distribution folder.
    pause
    exit /b 1
  )
)

if exist "%ROOT_DIR%\resources" (
  robocopy "%ROOT_DIR%\resources" "%ROOT_DIR%\dist\midas_floorload_auto_v4_debug\resources" /E /XD __pycache__ .pytest_cache /XF *.pyc *.pyo >nul
  if errorlevel 8 (
    echo [ERROR] Failed to copy resources to debug distribution folder.
    pause
    exit /b 1
  )
)

echo.
echo [SUCCESS] Debug build completed.
echo Output:
echo   dist\midas_floorload_auto_v4_debug\midas_floorload_auto_v4_debug.exe
pause
exit /b 0
