@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title ติดตั้งตัวช่วยของ Auto Link Photo

echo.
echo ==========================================================
echo    Auto Link Photo - ติดตั้งตัวช่วยภายนอก
echo ==========================================================
echo.
echo  สคริปต์นี้จะติดตั้งสองอย่างลงในเครื่องนี้
echo.
echo    yt-dlp   ตัวดาวน์โหลดสื่อ ใช้กับเว็บที่ไม่ยอมส่งไฟล์ให้ตรง ๆ
echo    ffmpeg   ตัวต่อและแปลงไฟล์ ใช้ตอนซ่อมไฟล์ให้เปิดได้
echo.
echo  ทั้งสองตัวเป็นโปรแกรมโอเพนซอร์ส ติดตั้งแยกจากตัวระบบ
echo  Auto Link Photo จะเรียกใช้เมื่อคุณสั่งเท่านั้น
echo.
echo ----------------------------------------------------------
echo.

rem ---------- ตรวจว่ามี Python หรือยัง ----------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo  [ไม่พบ Python]
    echo.
    echo  ต้องติดตั้ง Python ก่อน ดาวน์โหลดได้ที่ https://www.python.org/downloads/
    echo  ตอนติดตั้ง อย่าลืมติ๊ก "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
echo  พบ Python แล้ว: %PY%
echo.

rem ---------- ติดตั้ง yt-dlp ----------
echo  [1/2] กำลังติดตั้ง yt-dlp ...
%PY% -m pip install --upgrade --user yt-dlp
if errorlevel 1 (
    echo.
    echo  ติดตั้ง yt-dlp ไม่สำเร็จ ลองเปิดหน้าต่างนี้แบบ Run as administrator แล้วรันใหม่
    echo.
    pause
    exit /b 1
)
echo  ติดตั้ง yt-dlp เรียบร้อย
echo.

rem ---------- ตรวจ ffmpeg ----------
echo  [2/2] กำลังตรวจ ffmpeg ...
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo  ยังไม่พบ ffmpeg ในเครื่องนี้ กำลังลองติดตั้งให้
    where winget >nul 2>&1
    if errorlevel 1 (
        echo.
        echo  เครื่องนี้ไม่มี winget จึงติดตั้ง ffmpeg อัตโนมัติไม่ได้
        echo  ดาวน์โหลดเองได้ที่ https://www.gyan.dev/ffmpeg/builds/
        echo  แตกไฟล์แล้วเพิ่มโฟลเดอร์ bin ลงใน PATH
    ) else (
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    )
) else (
    echo  พบ ffmpeg อยู่แล้ว
)

echo.
echo ==========================================================
echo  เสร็จแล้ว
echo.
echo  ขั้นตอนต่อไป
echo    1. ปิดหน้าต่างนี้
echo    2. ปิดแล้วเปิด Auto Link Photo ใหม่
echo    3. เข้าโหมดวิดีโอ ค้นหาหน้าเว็บ แล้วดูแผง "ตัวช่วยภายนอก"
echo.
echo  ถ้าระบบยังบอกว่าไม่พบเครื่องมือ ให้ปิดเปิดเครื่องหนึ่งครั้ง
echo  เพื่อให้ Windows อ่านที่อยู่โปรแกรมใหม่
echo ==========================================================
echo.
pause
