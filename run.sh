#!/usr/bin/env sh
# DisputeGraph demo: no credentials needed (replays cached sandbox data)
set -e
pip install -q -r requirements.txt
echo "Open http://localhost:8000"
DEMO_MODE=1 LLM_MODEL="${LLM_MODEL:-nvidia/nemotron-3.5-lightning-30b-a3b}" python -m uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-8000}"
