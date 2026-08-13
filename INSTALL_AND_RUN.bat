@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title Donggeurami Editor v2.7.3 - Install and Run

call :find_python
if not defined PYEXE goto :no_python

echo.
echo [1/3] Python found:
echo       %PYEXE%
"%PYEXE%" --version
if errorlevel 1 goto :python_failed

echo.
echo [2/3] Checking required packages...
"%PYEXE%" -c "import flask,PIL,numpy,cv2,pikepdf,reportlab,filelock" >nul 2>nul
if errorlevel 1 (
    echo Required packages are missing. Installing now...
    "%PYEXE%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 goto :install_failed
) else (
    echo Required packages are already installed.
)

echo.
echo [3/3] Starting Donggeurami Editor...
echo Browser: http://127.0.0.1:5500
echo Keep this window open while using the editor.
echo.
"%PYEXE%" "%~dp0app.py"
set "EXITCODE=%ERRORLEVEL%"
echo.
echo Editor server stopped. Exit code: %EXITCODE%
pause
exit /b %EXITCODE%

:find_python
set "PYEXE="
for /f "usebackq delims=" %%P in (`py -3 -c "import sys;print(sys.executable)" 2^>nul`) do if exist "%%P" set "PYEXE=%%P"
if defined PYEXE goto :eof
for /f "usebackq delims=" %%P in (`python -c "import sys;print(sys.executable)" 2^>nul`) do if exist "%%P" set "PYEXE=%%P"
if defined PYEXE goto :eof
for /d %%D in ("%LocalAppData%\Programs\Python\Python*") do if exist "%%~fD\python.exe" set "PYEXE=%%~fD\python.exe"
if defined PYEXE goto :eof
for /d %%D in ("%ProgramFiles%\Python*") do if exist "%%~fD\python.exe" set "PYEXE=%%~fD\python.exe"
goto :eof

:no_python
echo.
echo [ERROR] Python 3 executable could not be found.
echo Install Python 3 from python.org and check "Add python.exe to PATH" during setup.
echo Then run INSTALL_AND_RUN.bat again.
pause
exit /b 1

:python_failed
echo.
echo [ERROR] The detected Python executable could not be started:
echo %PYEXE%
pause
exit /b 1

:install_failed
echo.
echo [ERROR] Package installation failed.
echo If the message above mentions permission, run this file again normally first,
echo or open Command Prompt in this folder and run:
echo "%PYEXE%" -m pip install -r requirements.txt
pause
exit /b 1
