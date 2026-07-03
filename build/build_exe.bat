@echo off
setlocal
cd /d "%~dp0\.."
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --windowed --name midas_floorload_auto_v4 ^
  --add-data "resources;resources" ^
  --add-data "legacy_v3;legacy_v3" ^
  --add-data "user_config;user_config" ^
  app\main.py
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)
echo Build complete: dist\midas_floorload_auto_v4\midas_floorload_auto_v4.exe
