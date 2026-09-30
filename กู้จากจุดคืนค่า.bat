@echo off
setlocal enabledelayedexpansion
title Restore Auto Link photo from a Windows snapshot

rem ================================================================
rem  Try to restore the folder from a Windows shadow copy (System
rem  Restore / Previous Versions). This needs NO second drive and
rem  writes nothing to C: until a good copy is actually found.
rem
rem  Just double-click. English only: cmd.exe garbles Thai in .bat.
rem ================================================================

net session >nul 2>&1
if errorlevel 1 (
    echo Asking for administrator rights. Click YES on the popup.
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "TARGET=C:\Users\Windows\Desktop\Auto Link photo"
set "LINK=C:\_alp_snapshot"

echo.
echo ================================================================
echo    RESTORE FROM WINDOWS SNAPSHOT
echo ================================================================
echo.
echo  Looking for snapshots of drive C ...
echo.

vssadmin list shadows /for=C: 2>nul | findstr /c:"Shadow Copy Volume" >nul
if errorlevel 1 (
    echo  ----------------------------------------------------------
    echo  NO SNAPSHOT FOUND.
    echo  System Protection is off on this PC, so Windows never kept
    echo  an older copy of the folder.
    echo.
    echo  Remaining option that can still work:
    echo    plug in ANY usb flash drive, then run  RECOVER  again.
    echo  ----------------------------------------------------------
    echo.
    pause
    exit /b 1
)

echo  Snapshots found:
echo.
vssadmin list shadows /for=C: | findstr /c:"creation time" /c:"Shadow Copy Volume"
echo.

set "SNAP="
for /f "tokens=4" %%i in ('vssadmin list shadows /for^=C: ^| findstr /c:"Shadow Copy Volume"') do set "SNAP=%%i"

if not defined SNAP (
    echo  Could not read the snapshot path.
    pause
    exit /b 1
)

echo  Using newest snapshot:
echo    !SNAP!
echo.

if exist "%LINK%" rmdir "%LINK%" 2>nul
mklink /d "%LINK%" "!SNAP!\" >nul
if errorlevel 1 (
    echo  Could not open the snapshot.
    pause
    exit /b 1
)

set "SRC=%LINK%\Users\Windows\Desktop\Auto Link photo"
if not exist "%SRC%" (
    echo  ----------------------------------------------------------
    echo  The snapshot exists but does not contain that folder.
    echo  It was probably taken before the folder was created.
    echo  ----------------------------------------------------------
    rmdir "%LINK%" 2>nul
    echo.
    pause
    exit /b 1
)

echo  FOUND IT. Files inside the snapshot:
echo.
dir /b "%SRC%"
echo.
echo  Copying them back now...
echo.
robocopy "%SRC%" "%TARGET%" /E /R:1 /W:1 /NFL /NDL /NJH
rmdir "%LINK%" 2>nul

echo.
echo ================================================================
echo  DONE. Files restored to:
echo    %TARGET%
echo.
echo  Open that folder and check. Then tell me.
echo ================================================================
echo.
pause
