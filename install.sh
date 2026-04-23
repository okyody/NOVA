#!/usr/bin/env bash
set -euo pipefail

echo "== NOVA install (Linux/macOS) =="

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: Python 3.11+ is required."
  exit 1
fi

PY_VERSION="$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")"
echo "Found Python ${PY_VERSION}"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing NOVA dependencies..."
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

if [ ! -f "nova.config.json" ]; then
  cp nova.config.example.json nova.config.json
  echo "Created nova.config.json"
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Created .env"
fi

echo "Running startup smoke test..."
python -m pytest tests/test_api_smoke.py -q

echo
echo "Install complete."
echo "Next steps:"
echo "  1. ollama pull qwen2.5:14b"
echo "  2. edit nova.config.json"
echo "  3. python -m apps.nova_server.main"
echo "  4. curl http://127.0.0.1:8765/health"
