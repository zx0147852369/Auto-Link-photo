@echo off
title Rebuild project files from chat history

set PY=
where py >nul 2>&1
if not errorlevel 1 set PY=py -3
if "%PY%"=="" (
  where python >nul 2>&1
  if not errorlevel 1 set PY=python
)
if "%PY%"=="" (
  echo.
  echo  Python not found on this PC.
  echo  Install from https://www.python.org/downloads/
  echo  and tick "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

%PY% "%~dp0restore.py"

echo.
echo  Report saved as  _restore_report.txt
echo.
pause
