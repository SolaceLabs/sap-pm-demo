#!/bin/bash
# Helper script to run the maintenance agent
# Usage: ./run_agent.sh

set -e

cd "$(dirname "$0")"

# Check that .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found in $(pwd)"
    echo "Copy .env.example to .env and fill in your credentials:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
fi

# Verify Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
REQUIRED="3.11"
if [ "$(printf '%s\n' "$REQUIRED" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED" ]; then
    echo "WARNING: Python $REQUIRED+ recommended, you have $PYTHON_VERSION"
fi

echo "Starting maintenance agent..."
python3 agent.py
