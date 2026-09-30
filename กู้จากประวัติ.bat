@echo off
chcp 65001 >nul
title Rebuild project files from chat history

rem  Launcher only. All Thai text lives in the .py file,
rem  because cmd.exe garbles Thai inside .bat files.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo  Python not found on this PC.
    echo  Install it from https://www.python.org/downloads/
    echo  and tick "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

%PY% "%~dp0\กู้จากประวัติ.py"

echo.
pause
