#!/usr/bin/env bash
# NOVA Install Script (Linux/macOS)
set -e

echo "═══════════════════════════════════"
echo "  NOVA — Installation Script"
echo "═══════════════════════════════════"

# Check Python version
if ! command -v python3 &>/dev/null; then
    echo "Error: Python 3.11+ is required but not found."
    echo "Install it from: https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Found Python $PY_VERSION"

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Install dependencies
echo "Installing NOVA dependencies..."
pip install -e ".[dev]"

# Copy config if not exists
if [ ! -f "nova.config.json" ]; then
    echo "Creating default configuration..."
    cp nova.config.example.json nova.config.json
    echo "Created nova.config.json — edit it with your platform credentials."
fi

# Copy .env if not exists
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Created .env — edit it with your settings."
fi

echo ""
echo "═══════════════════════════════════"
echo "  Installation Complete!"
echo "═══════════════════════════════════"
echo ""
echo "Next steps:"
echo "  1. Start Ollama:     ollama pull qwen2.5:14b"
echo "  2. Edit config:      nano nova.config.json"
echo "  3. Start NOVA:       python -m apps.nova_server.main"
echo ""
