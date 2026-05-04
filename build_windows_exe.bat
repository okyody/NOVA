@echo off
setlocal

echo == NOVA Windows EXE build ==

if not exist ".venv\Scripts\python.exe" (
    echo Error: .venv is missing. Run install.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

echo Installing PyInstaller...
python -m pip install pyinstaller
if %errorlevel% neq 0 (
    echo Failed to install PyInstaller.
    exit /b 1
)

if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

echo Building NOVA.exe...
pyinstaller NOVA.spec --noconfirm
if %errorlevel% neq 0 (
    echo EXE build failed.
    exit /b 1
)

echo.
echo Build complete:
echo   dist\NOVA\NOVA.exe
endlocal
