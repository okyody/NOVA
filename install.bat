@echo off
setlocal

echo == NOVA install (Windows) ==

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python 3.11+ is required.
    exit /b 1
)

python --version

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing NOVA dependencies...
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if not exist "nova.config.json" (
    copy nova.config.example.json nova.config.json >nul
    echo Created nova.config.json
)

if not exist ".env" (
    copy .env.example .env >nul
    echo Created .env
)

echo Running startup smoke test...
python -m pytest tests\test_api_smoke.py -q
if %errorlevel% neq 0 (
    echo Smoke test failed.
    exit /b 1
)

echo.
echo Install complete.
echo Next steps:
echo   1. ollama pull qwen2.5:14b
echo   2. edit nova.config.json
echo   3. python -m apps.nova_server.main
echo   4. curl http://127.0.0.1:8765/health
endlocal
