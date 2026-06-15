#!/bin/bash
# Launch the dispatch arbitrator service
set -e
cd "$(dirname "$0")"
source ../agent/.venv/bin/activate
python dispatch_arbitrator.py
