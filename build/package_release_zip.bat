@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%" || (
  echo [ERROR] Cannot move to project root.
  pause
  exit /b 1
)

set "VERSION=1.0.0"
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
echo [INFO] Step 1/3: Build GUI distribution...
call "%ROOT_DIR%\build\build_exe.bat"
if errorlevel 1 (
  echo [ERROR] Build failed.
  pause
  exit /b 1
)

echo [INFO] Step 2/3: Validate distribution folder...
%PY_RUN% "%ROOT_DIR%\build\validate_distribution.py" "%ROOT_DIR%\dist\midas_floorload_auto_v4"
if errorlevel 1 (
  echo [ERROR] Distribution validation failed.
  pause
  exit /b 1
)

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmm"') do set "STAMP=%%I"

set "RELEASE_DIR=%ROOT_DIR%\dist_release"
set "ZIP_PATH=%RELEASE_DIR%\MIDAS_FLOOR_LOAD_TOOL_v%VERSION%_%STAMP%.zip"

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

echo [INFO] Step 3/3: Create release zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -Path '%ROOT_DIR%\dist\midas_floorload_auto_v4' -DestinationPath '%ZIP_PATH%' -Force"

if errorlevel 1 (
  echo [ERROR] ZIP creation failed.
  pause
  exit /b 1
)

if not exist "%ZIP_PATH%" (
  echo [ERROR] ZIP file was not created.
  pause
  exit /b 1
)

echo.
echo [SUCCESS] Release ZIP created:
echo   %ZIP_PATH%
echo.
echo Employee instruction:
echo   1. Extract this ZIP once.
echo   2. Open the midas_floorload_auto_v4 folder.
echo   3. Run midas_floorload_auto_v4.exe.
echo.
echo Do NOT extract _internal\base_library.zip.
echo It is a required runtime file used by the exe.
echo.
echo Send this ZIP to employees. Do NOT send files from the build folder.
pause
exit /b 0
