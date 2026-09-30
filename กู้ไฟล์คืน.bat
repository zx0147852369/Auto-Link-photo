@echo off
setlocal enabledelayedexpansion
title Recover Auto Link photo

rem ================================================================
rem  Recover deleted files from C:\Users\Windows\Desktop\Auto Link photo
rem
rem  Just double-click this file. Nothing to type.
rem  English only on purpose: cmd.exe garbles Thai text in .bat files.
rem ================================================================

net session >nul 2>&1
if errorlevel 1 (
    echo Asking for administrator rights. Click YES on the popup.
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ================================================================
echo    RECOVER  Auto Link photo
echo ================================================================
echo.

rem ---------- find a destination drive (must not be C:) ----------
set "DEST="
for %%D in (D E F G H I J K L M N O P Q R S T U V W X Y Z) do (
    if not defined DEST if exist %%D:\ set "DEST=%%D"
)

if not defined DEST (
    echo  [CANNOT START YET - need a second drive]
    echo.
    echo  This PC only has drive C.
    echo  The recovery tool must not write to the same drive it reads,
    echo  or it will overwrite the very files we are trying to save.
    echo.
    echo  Plug in a USB flash drive, then run this file again.
    echo.
    pause
    exit /b 1
)
echo  Recovered files will be written to  %DEST%:\
echo.

rem ---------- make sure the recovery tool exists ----------
where winfr >nul 2>&1
if errorlevel 1 (
    echo  Recovery tool not found. Installing it now...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  winget is not available on this PC.
        echo  Open Microsoft Store, search for:  Windows File Recovery
        echo  Install it, then run this file again.
        echo.
        pause
        exit /b 1
    )
    winget install --id Microsoft.WindowsFileRecovery -e --accept-source-agreements --accept-package-agreements
    where winfr >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  Installed, but not callable yet.
        echo  Close this window and run this file again.
        echo.
        pause
        exit /b 1
    )
)
echo  Recovery tool is ready.
echo.

echo ----------------------------------------------------------------
echo  PASS 1 of 2   quick scan
echo  Do not save any new files to drive C while this runs.
echo ----------------------------------------------------------------
echo.
echo y| winfr C: %DEST%:\Recover1 /regular /n "\Users\Windows\Desktop\Auto Link photo\"

echo.
echo ----------------------------------------------------------------
echo  PASS 2 of 2   deep scan  (slower, finds what pass 1 missed)
echo ----------------------------------------------------------------
echo.
echo y| winfr C: %DEST%:\Recover2 /extensive /n *.py /n *.json /n *.html /n *.css /n *.md /n *.bat

echo.
echo ================================================================
echo  DONE
echo.
echo  Look in these two folders:
echo    %DEST%:\Recover1
echo    %DEST%:\Recover2
echo.
echo  Tell me what you find, especially:
echo    app.py   scraper.py   videoscan.py   helper.py   render.py
echo ================================================================
echo.
pause
