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

if not exist "%ROOT_DIR%\requirements.txt" (
  echo [ERROR] requirements.txt was not found in the project root.
  pause
  exit /b 1
)

if not exist "%ROOT_DIR%\midas_floorload_auto_v4.spec" (
  echo [ERROR] midas_floorload_auto_v4.spec was not found in the project root.
  pause
  exit /b 1
)

echo [INFO] Removing stale PyInstaller build/dist folders...
if exist "%ROOT_DIR%\build\midas_floorload_auto_v4" rmdir /s /q "%ROOT_DIR%\build\midas_floorload_auto_v4"
if exist "%ROOT_DIR%\dist\midas_floorload_auto_v4" rmdir /s /q "%ROOT_DIR%\dist\midas_floorload_auto_v4"

echo [INFO] Recording source/build version information...
%PY_RUN% "%ROOT_DIR%\build\generate_build_info.py"
if errorlevel 1 (
  echo [ERROR] Failed to generate build_info.json.
  pause
  exit /b 1
)

echo [INFO] Building GUI distribution with PyInstaller...
%PY_RUN% -m PyInstaller --noconfirm --clean "%ROOT_DIR%\midas_floorload_auto_v4.spec"
if errorlevel 1 (
  echo [ERROR] PyInstaller build failed.
  pause
  exit /b 1
)

if not exist "%ROOT_DIR%\dist\midas_floorload_auto_v4\midas_floorload_auto_v4.exe" (
  echo [ERROR] Build finished, but output exe was not found.
  echo Expected: dist\midas_floorload_auto_v4\midas_floorload_auto_v4.exe
  pause
  exit /b 1
)

echo [INFO] Finalizing EXE timestamp/hash information...
%PY_RUN% "%ROOT_DIR%\build\generate_build_info.py" --exe "%ROOT_DIR%\dist\midas_floorload_auto_v4\midas_floorload_auto_v4.exe"
if errorlevel 1 (
  echo [ERROR] Failed to finalize build_info.json.
  pause
  exit /b 1
)
copy /Y "%ROOT_DIR%\build_info.json" "%ROOT_DIR%\dist\midas_floorload_auto_v4\build_info.json" >nul
if errorlevel 1 (
  echo [ERROR] Failed to copy build_info.json to the distribution folder.
  pause
  exit /b 1
)

echo [INFO] Copying runtime data folders to dist root...
if exist "%ROOT_DIR%\legacy_v3" (
  robocopy "%ROOT_DIR%\legacy_v3" "%ROOT_DIR%\dist\midas_floorload_auto_v4\legacy_v3" /E /XD __pycache__ .pytest_cache tests /XF *.pyc *.pyo >nul
  if errorlevel 8 (
    echo [ERROR] Failed to copy legacy_v3 to distribution folder.
    pause
    exit /b 1
  )
) else (
  echo [ERROR] Required folder not found: legacy_v3
  pause
  exit /b 1
)

if not exist "%ROOT_DIR%\dist\midas_floorload_auto_v4\user_config" mkdir "%ROOT_DIR%\dist\midas_floorload_auto_v4\user_config"
if exist "%ROOT_DIR%\user_config" (
  robocopy "%ROOT_DIR%\user_config" "%ROOT_DIR%\dist\midas_floorload_auto_v4\user_config" *.json /E /XF *.local.json >nul
  if errorlevel 8 (
    echo [ERROR] Failed to copy user_config to distribution folder.
    pause
    exit /b 1
  )
)

if exist "%ROOT_DIR%\resources" (
  robocopy "%ROOT_DIR%\resources" "%ROOT_DIR%\dist\midas_floorload_auto_v4\resources" /E /XD __pycache__ .pytest_cache /XF *.pyc *.pyo >nul
  if errorlevel 8 (
    echo [ERROR] Failed to copy resources to distribution folder.
    pause
    exit /b 1
  )
)

echo [INFO] Validating distribution folder...
%PY_RUN% "%ROOT_DIR%\build\validate_distribution.py" "%ROOT_DIR%\dist\midas_floorload_auto_v4"
if errorlevel 1 (
  echo [ERROR] Distribution validation failed.
  pause
  exit /b 1
)

echo.
echo [SUCCESS] Build completed.
echo Output folder:
echo   dist\midas_floorload_auto_v4
echo.
echo IMPORTANT:
echo   Send the entire dist\midas_floorload_auto_v4 folder to employees.
echo   Do NOT send build\midas_floorload_auto_v4 or only the exe file.
echo   Do NOT extract _internal\base_library.zip.
pause
exit /b 0
