@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title Donggeurami Editor v2.7.3

set "PYEXE="
for /f "usebackq delims=" %%P in (`py -3 -c "import sys;print(sys.executable)" 2^>nul`) do if exist "%%P" set "PYEXE=%%P"
if not defined PYEXE for /f "usebackq delims=" %%P in (`python -c "import sys;print(sys.executable)" 2^>nul`) do if exist "%%P" set "PYEXE=%%P"
if not defined PYEXE for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do if exist "%%~fD\python.exe" set "PYEXE=%%~fD\python.exe"

if not defined PYEXE (
  echo [ERROR] Python 3 was not found. Run INSTALL_AND_RUN.bat first.
  pause
  exit /b 1
)

"%PYEXE%" -c "import flask" >nul 2>nul
if errorlevel 1 (
  echo Required packages are not installed. Starting installer...
  call "%~dp0INSTALL_AND_RUN.bat"
  exit /b %ERRORLEVEL%
)

echo Starting Donggeurami Editor...
echo Browser: http://127.0.0.1:5500
"%PYEXE%" "%~dp0app.py"
pause
