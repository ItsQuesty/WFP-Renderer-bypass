@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

echo ============================================
echo   WFP Compiler Workspace Cleanup (Safe)
echo ============================================
echo.
echo This removes non-core generated clutter:
echo - build folders (build*, dist*)
echo - test/cache folders (__pycache__, .pytest_cache, etc.)
echo - copied/export folders (gitcopy)
echo - temp artifact files (*.pyc, *.pyo, *.log, .coverage*)
echo.

set "TARGET_COUNT=0"

call :QueueDir "build"
call :QueueDir "build_*"
call :QueueDir "dist"
call :QueueDir "dist_*"
call :QueueDir "gitcopy"
call :QueueDir ".pytest_cache"
call :QueueDir ".mypy_cache"
call :QueueDir ".ruff_cache"
call :QueueDir "htmlcov"

for /d /r %%D in (__pycache__) do call :QueueAbs "%%~fD"

for %%F in (*.pyc *.pyo *.log .coverage .coverage.*) do call :QueueFile "%%~fF"

if %TARGET_COUNT% EQU 0 (
  echo No cleanup targets found.
  exit /b 0
)

echo.
echo Found %TARGET_COUNT% target(s).
echo.
set /p "CONFIRM=Proceed with deletion? (Y/N): "
if /I not "%CONFIRM%"=="Y" (
  echo Aborted. No files were deleted.
  exit /b 0
)

echo.
for /L %%I in (1,1,%TARGET_COUNT%) do (
  set "ENTRY=!TARGET_%%I!"
  set "KIND=!KIND_%%I!"
  if /I "!KIND!"=="DIR" (
    if exist "!ENTRY!" (
      rd /s /q "!ENTRY!" 2>nul
      if exist "!ENTRY!" (
        echo [WARN] Failed to remove folder: !ENTRY!
      ) else (
        echo [OK] Removed folder: !ENTRY!
      )
    )
  ) else (
    if exist "!ENTRY!" (
      del /f /q "!ENTRY!" 2>nul
      if exist "!ENTRY!" (
        echo [WARN] Failed to remove file: !ENTRY!
      ) else (
        echo [OK] Removed file: !ENTRY!
      )
    )
  )
)

echo.
echo Cleanup complete.
exit /b 0

:QueueDir
for /d %%D in (%~1) do call :QueueAbs "%%~fD"
exit /b 0

:QueueAbs
set /a TARGET_COUNT+=1
set "TARGET_%TARGET_COUNT%=%~1"
set "KIND_%TARGET_COUNT%=DIR"
echo [DIR ] %~1
exit /b 0

:QueueFile
set /a TARGET_COUNT+=1
set "TARGET_%TARGET_COUNT%=%~1"
set "KIND_%TARGET_COUNT%=FILE"
echo [FILE] %~1
exit /b 0
