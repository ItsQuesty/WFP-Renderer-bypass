@echo off
setlocal

echo.
echo ============================================
echo        dummy autocompile activated
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found in PATH.
  echo Install Python 3.10+ and try again.
  exit /b 1
)

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
  echo [INFO] PyInstaller not found. Installing...
  python -m pip install pyinstaller
  if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    exit /b 1
  )
)

if not exist "WfpCompiler.spec" (
  echo [ERROR] WfpCompiler.spec not found.
  echo Run this script from the project root folder.
  exit /b 1
)

echo [INFO] Building WfpCompiler.exe...
python -m PyInstaller --noconfirm WfpCompiler.spec
if errorlevel 1 (
  echo [ERROR] Build failed.
  exit /b 1
)

echo.
echo [OK] Build complete.
echo Output: dist\WfpCompiler.exe
echo.
pause
