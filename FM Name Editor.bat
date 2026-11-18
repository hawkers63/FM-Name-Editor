@echo off
SETLOCAL EnableExtensions DisableDelayedExpansion
:: ==============================================================
::  FM Name Editor.bat  v3.1  -  launcher for fm_name_editor.py
::
::  Copyright (c) 2026 onwards Mark Hawksworth (hawkers63).
::  All rights reserved. Proprietary software, not open source.
::  See LICENSE.
::
::  Checks Python and PySide6, offers to install PySide6 if it
::  is missing, then starts the app. Drag .lnc files onto this
::  file to open them straight away.
:: ==============================================================

:: ---- Paths and settings --------------------------------------
rem Prefer the interpreter on PATH. Fall back to the known 3.11 install.
set "PY="
for /f "delims=" %%I in ('where python 2^>nul') do (
    if not defined PY set "PY=%%I"
)
if not defined PY set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
set "APPDIR=C:\FM Name Editor"
set "APP=%APPDIR%\fm_name_editor.py"

title FM Name Editor - launcher
color 0B

:: ---- Checks --------------------------------------------------
:check_python
if not exist "%PY%" goto no_python
if not exist "%APP%" goto no_app

:check_pyside
"%PY%" -c "import PySide6.QtWidgets" >nul 2>&1
if errorlevel 1 goto offer_install
goto launch

:: ---- Offer to install PySide6 --------------------------------
:offer_install
cls
echo.
echo  PySide6 is not installed for:
echo    %PY%
echo.
echo  FM Name Editor needs it for its window.
echo.
choice /c YN /n /m "  Install PySide6 now with pip? [Y/N] "
if errorlevel 2 goto cancelled
echo.
"%PY%" -m pip install PySide6
if errorlevel 1 goto install_failed
"%PY%" -c "import PySide6.QtWidgets" >nul 2>&1
if errorlevel 1 goto install_failed
echo.
echo  PySide6 installed.
goto launch

:: ---- Launch --------------------------------------------------
:launch
cd /d "%APPDIR%"
echo Starting FM Name Editor...
"%PY%" "%APP%" %*
if errorlevel 1 goto app_error
goto end

:: ---- Messages ------------------------------------------------
:no_python
color 0C
echo Python was not found on PATH or at the fallback location:
echo   %PY%
echo Edit the PY line at the top of this file.
pause
goto end

:no_app
color 0C
echo Could not find:
echo   %APP%
pause
goto end

:install_failed
color 0C
echo.
echo  PySide6 could not be installed. See the pip messages above.
pause
goto end

:cancelled
echo.
echo  Cancelled. The app cannot start without PySide6.
pause
goto end

:app_error
color 0E
echo.
echo  FM Name Editor closed with an error. See the messages above.
pause
goto end

:end
ENDLOCAL
exit /b 0
