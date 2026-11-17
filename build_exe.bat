@echo off
SETLOCAL EnableExtensions DisableDelayedExpansion
:: ==============================================================
::  build_exe.bat  -  build FM Name Editor.exe with PyInstaller
::
::  Copyright (c) 2026 onwards Mark Hawksworth (hawkers63).
::  All rights reserved. Proprietary software, not open source.
::  See LICENSE.
::
::  PyInstaller is a build tool only; the runtime still needs
::  only PySide6. The exe is a one-file windowed build of
::  fm_name_editor.py, carrying icon\football.ico and a Windows
::  version resource with the copyright above. The result lands
::  in dist\FM Name Editor.exe.
:: ==============================================================

set "PY="
for /f "delims=" %%I in ('where python 2^>nul') do (
    if not defined PY set "PY=%%I"
)
if not defined PY set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" (
    color 0C
    echo Python was not found on PATH or at the fallback location:
    echo   %PY%
    echo Install Python 3.11 or edit the PY line at the top of this file.
    pause
    exit /b 1
)

"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller is not installed for:
    echo   %PY%
    echo Install it with:
    echo   "%PY%" -m pip install pyinstaller
    pause
    exit /b 1
)

cd /d "%~dp0"
"%PY%" -m PyInstaller --noconfirm --clean "FM Name Editor.spec"
if errorlevel 1 (
    color 0C
    echo PyInstaller failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo Built:  dist\FM Name Editor.exe
exit /b 0
