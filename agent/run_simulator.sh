#!/bin/bash
# Helper script to run the sensor simulator
# Usage: ./run_simulator.sh

set -e

cd "$(dirname "$0")"

# Check that .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found in $(pwd)"
    echo "Copy .env.example to .env and fill in your credentials"
    exit 1
fi

echo "Starting sensor simulator..."
python3 simulator/sensor_sim.py
