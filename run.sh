#!/usr/bin/env sh
# DisputeGraph demo: no credentials needed (replays cached sandbox data)
set -e
pip install -q -r requirements.txt
echo "Open http://localhost:8000"
DEMO_MODE=1 python -m uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-8000}"
