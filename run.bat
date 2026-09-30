@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===============================================
echo   Image Link Extractor
echo ===============================================
echo.
echo [1/2] ตรวจสอบและติดตั้งไลบรารี...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo ติดตั้งไม่สำเร็จ - กรุณาตรวจสอบว่าติดตั้ง Python แล้ว
    pause
    exit /b 1
)
echo [2/2] เริ่มเซิร์ฟเวอร์...
echo.
start "" http://127.0.0.1:5000
python app.py
pause
