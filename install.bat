@echo off
REM NOVA Install Script (Windows)
echo ═══════════════════════════════════
echo   NOVA - Installation Script
echo ═══════════════════════════════════

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python 3.11+ is required but not found.
    echo Install it from: https://www.python.org/downloads/
    pause
    exit /b 1
)

python --version

REM Create virtual environment
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate venv
call .venv\Scripts\activate.bat

REM Install dependencies
echo Installing NOVA dependencies...
pip install -e ".[dev]"

REM Copy config if not exists
if not exist "nova.config.json" (
    echo Creating default configuration...
    copy nova.config.example.json nova.config.json
    echo Created nova.config.json - edit it with your platform credentials.
)

REM Copy .env if not exists
if not exist ".env" (
    copy .env.example .env
    echo Created .env - edit it with your settings.
)

echo.
echo ═══════════════════════════════════
echo   Installation Complete!
echo ═══════════════════════════════════
echo.
echo Next steps:
echo   1. Start Ollama:     ollama pull qwen2.5:14b
echo   2. Edit config:      notepad nova.config.json
echo   3. Start NOVA:       python -m apps.nova_server.main
echo.
pause
