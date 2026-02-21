@echo off
setlocal

echo ============================================
echo   BurnBar - Build Script
echo ============================================
echo.

echo [1/3] Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo [2/3] Installing PyInstaller...
pip install pyinstaller
if errorlevel 1 goto :error

echo.
echo [3/3] Building BurnBar.exe...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name BurnBar ^
    --hidden-import pystray._win32 ^
    --add-data "burnbar;burnbar" ^
    main.pyw
if errorlevel 1 goto :error

echo.
echo ============================================
echo   Build successful!
echo   Output: dist\BurnBar.exe
echo ============================================
goto :end

:error
echo.
echo BUILD FAILED -- see errors above.

:end
pause
