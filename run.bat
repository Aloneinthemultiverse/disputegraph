@echo off
REM DisputeGraph demo: no credentials needed (replays cached sandbox data)
pip install -q -r requirements.txt
set DEMO_MODE=1
if not defined LLM_MODEL set LLM_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b
echo Open http://localhost:8000
python -m uvicorn backend.app:app --port 8000
